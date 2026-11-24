import re
from collections import Counter, defaultdict
from math import prod
from pathlib import Path

import onnx
from onnx import AttributeProto, TensorProto, numpy_helper

from .schema import Graph, GraphNode, ModelArtifact, QuantizationInfo, SemanticModule, TensorInfo

QDQ = {"QuantizeLinear", "DequantizeLinear"}


def read_model(path: Path):
    model = onnx.load(path, load_external_data=False)
    for tensor in onnx.external_data_helper._get_all_tensors(model):
        if tensor.data_location == TensorProto.EXTERNAL:
            location = next((x.value for x in tensor.external_data if x.key == "location"), "")
            target = (path.parent / location).resolve()
            if not location or Path(location).is_absolute() or not target.is_relative_to(path.parent.resolve()):
                raise ValueError("ONNX external tensor must reside beside the model")
    onnx.external_data_helper.load_external_data_for_model(model, str(path.parent))
    onnx.checker.check_model(model)
    return model


def parse_encodings(data):
    if not isinstance(data, dict):
        raise ValueError("Expected AIMET encoding object")
    result = []
    def vector(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return [value]
        if isinstance(value, list) and all(isinstance(item, (int, float)) for item in value):
            return value
        return None

    for section in ("activation_encodings", "param_encodings", "encodings"):
        records = data.get(section, {})
        if not isinstance(records, (dict, list)):
            raise ValueError(f"Invalid AIMET {section}")
        if isinstance(records, list):
            if any(not isinstance(record, dict) for record in records):
                raise ValueError(f"Invalid AIMET {section} record")
            records = [(record.get("name"), record) for record in records]
        else:
            records = records.items()
        for name, encoding in records:
            first = encoding[0] if isinstance(encoding, list) and encoding else encoding
            if not isinstance(name, str) or not name or not isinstance(first, dict):
                raise ValueError(f"Invalid AIMET {section} record")
            dtype = first.get("output_dtype", first.get("dtype"))
            width = re.match(r"(?:u?int|float)(\d+)", dtype) if isinstance(dtype, str) else None
            scale = first.get("y_scale", first.get("scale"))
            if isinstance(encoding, list) and len(encoding) > 1:
                scale = [record.get("scale") for record in encoding if isinstance(record, dict)]
            result.append(QuantizationInfo(
                format="AIMET", tensor=name, encoding=encoding, axis=first.get("axis"), dtype=dtype,
                bitwidth=first.get("bw", first.get("bitwidth", int(width.group(1)) if width else None)),
                scale=vector(scale), zero_point=vector(first.get("y_zero_point")),
            ))
    if not result:
        raise ValueError("No AIMET activation or parameter encodings")
    return result


def module_name(node):
    tokens = [value for value in node.name.split("/") if value]
    layer = re.search(r"(?:^|[/.])(?:layers?|blocks?|h)[/.](\d+)(?=[/.])", node.name)
    aliases = {"self_attn": "attention", "self_attention": "attention", "attn": "attention",
               "feed_forward": "mlp", "ffn": "mlp"}
    for token in tokens[:-1]:
        token = aliases.get(token, token)
        if token in {"input_projection", "attention", "mlp", "output_projection", "residual_attn", "residual_mlp"}:
            return f"layer.{layer[1]}.{token}" if layer else token
    if layer:
        return f"layer.{layer[1]}.other"
    for names in ([node.name], node.output, node.input):
        features = {match.group(1) for name in names for match in re.finditer(r"(?:^|[./_])features[./](\d+)(?=[./_]|$)", name)}
        if len(features) == 1:
            return f"features.{features.pop()}"
        if any(re.search(r"(?:^|[./_])classifier(?=[./_]|$)", name) for name in names):
            return "classifier"
    return "convolution" if node.op_type == "Conv" else "graph"


def inspect(model, artifact: ModelArtifact, encodings=None):
    issue = None
    try:
        model = onnx.shape_inference.infer_shapes(model)
    except (ValueError, RuntimeError, onnx.onnx_cpp2py_export.shape_inference.InferenceError) as exc:
        issue = str(exc)
    graph = model.graph
    tensors = {}
    for value in [*graph.input, *graph.value_info, *graph.output]:
        info = value.type.tensor_type
        dims = [d.dim_value if d.HasField("dim_value") else d.dim_param or None for d in info.shape.dim]
        tensors[value.name] = TensorInfo(
            name=value.name, shape=dims if info.HasField("shape") else None,
            dtype=TensorProto.DataType.Name(info.elem_type) if info.elem_type else None,
        )
    constants = {tensor.name: tensor for tensor in graph.initializer}
    for name, tensor in constants.items():
        tensors[name] = TensorInfo(name=name, shape=list(tensor.dims), dtype=TensorProto.DataType.Name(tensor.data_type),
                                   initializer_elements=prod(tensor.dims))
    for node in graph.node:
        for name in [*node.input, *node.output]:
            if name and name not in tensors:
                tensors[name] = TensorInfo(name=name)
        if node.op_type == "Constant" and node.output:
            value = next((attr.t for attr in node.attribute if attr.name == "value" and attr.type == AttributeProto.TENSOR), None)
            if value is not None:
                constants[node.output[0]] = value

    def values(name):
        if name not in constants:
            return None
        return numpy_helper.to_array(constants[name]).reshape(-1).tolist()

    quantization = list(encodings or [])
    quant_index = defaultdict(list)
    for index, encoding in enumerate(quantization):
        quant_index[encoding.tensor].append(index)
    for node in graph.node:
        if node.op_type not in QDQ:
            continue
        tensor, scale, *rest = node.input
        zero = rest[0] if rest and rest[0] else None
        quantized = node.output[0] if node.op_type == "QuantizeLinear" else tensor
        dtype = tensors[quantized].dtype
        axis = next((attr.i for attr in node.attribute if attr.name == "axis"), None)
        scales = values(scale)
        if axis is None and scales is not None and len(scales) > 1:
            axis = 1
        idx = len(quantization)
        quantization.append(QuantizationInfo(
            format="QDQ", tensor=tensor, operation=node.op_type, scale_tensor=scale, zero_point_tensor=zero,
            scale=scales, zero_point=values(zero), axis=axis, dtype=dtype,
            bitwidth={"UINT8": 8, "INT8": 8, "UINT16": 16, "INT16": 16, "INT32": 32, "INT4": 4, "UINT4": 4}.get(dtype),
        ))
        for name in {tensor, *node.output}:
            quant_index[name].append(idx)

    nodes = []
    modules = defaultdict(list)
    producer = {name: f"n{i}" for i, node in enumerate(graph.node) for name in node.output if name}
    for i, node in enumerate(graph.node):
        node_id = f"n{i}"
        module = module_name(node)
        modules[module].append(node_id)
        nodes.append(GraphNode(
            id=node_id, name=node.name, op=node.op_type, domain=node.domain, module=module,
            inputs=list(node.input), outputs=list(node.output),
            predecessors=list(dict.fromkeys(producer[name] for name in node.input if name in producer)),
            quantization=sorted({idx for name in [*node.input, *node.output] for idx in quant_index[name]}),
        ))
    kinds = {name.rsplit(".", 1)[-1] for name in modules}
    architecture = "Transformer" if {"attention", "mlp"} <= kinds else "ONNX graph"
    return Graph(
        artifact=artifact, architecture=architecture, nodes=nodes, tensors=tensors,
        modules=[SemanticModule(id=name, kind=name.rsplit(".", 1)[-1] if name.startswith("layer.") else name.split(".")[0],
                                parent=name.rsplit(".", 1)[0] if name.startswith("layer.") else architecture, nodes=ids)
                 for name, ids in modules.items()],
        inputs=[v.name for v in graph.input if v.name not in constants], outputs=[v.name for v in graph.output],
        initializer_elements=sum(prod(t.dims) for t in graph.initializer),
        quantization=quantization, shape_inference_issue=issue,
    )


def diff(left: Graph, right: Graph):
    def signature(node):
        return (node.module, node.domain, node.op)
    def wiring(model):
        labels = {}
        occurrences = Counter()
        for node in model.nodes:
            identity = (node.module, node.domain, node.op, node.name)
            occurrences[identity] += 1
            labels[node.id] = (*identity, occurrences[identity])
        return {(labels[parent], labels[node.id]) for node in model.nodes for parent in node.predecessors}

    def edges(records):
        return [{"from": source, "to": target} for source, target in sorted(records)]

    a = Counter(signature(node) for node in left.nodes)
    b = Counter(signature(node) for node in right.nodes)
    old_edges, new_edges = wiring(left), wiring(right)
    return {
        "baseline_nodes": len(left.nodes), "candidate_nodes": len(right.nodes),
        "edges_added": edges(new_edges - old_edges), "edges_removed": edges(old_edges - new_edges),
        "operator_changes": [
            {"module": key[0], "domain": key[1], "op": key[2], "baseline": a[key], "candidate": b[key]}
            for key in sorted(a.keys() | b.keys()) if a[key] != b[key]
        ],
    }
