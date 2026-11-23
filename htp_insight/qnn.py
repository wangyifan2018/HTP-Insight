import csv
import hashlib
import io
from collections import defaultdict

from .profiles import chrome_events

TRACE_HEADER = ["Current name", "Current type", "Source name", "Source type"]


def framework_operations(raw: bytes) -> dict[str, set[str]]:
    rows = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    if not any(row == TRACE_HEADER for row in rows):
        raise ValueError("DLC info CSV is missing the framework-trace table")
    operations = defaultdict(set)
    name, kind = None, None
    for row in rows:
        if len(row) != 4:
            break
        current, category, source, source_type = row
        if current:
            name, kind = current, category
        if kind == "OP" and source_type == "OP" and source:
            operations[name].add(source)
    return dict(operations)


def optrace_onnx_mappings(trace: bytes, framework_csv: bytes, graph) -> list[dict]:
    """Join explicit Optrace QNN names to DLC framework-trace rows and unique ONNX names."""
    sources = framework_operations(framework_csv)
    onnx_nodes = defaultdict(list)
    for node in graph.nodes:
        onnx_nodes[node.name].append(node.id)
    qnn_names = defaultdict(set)
    for _, _, _, _, _, args in chrome_events(trace):
        native_id, qnn_name = args.get("ID"), args.get("QNN Op Name")
        if "Duration (cycles)" in args and isinstance(native_id, str) and isinstance(qnn_name, str):
            qnn_names[native_id].add(qnn_name)
    fingerprint = hashlib.sha256(framework_csv).hexdigest()
    mappings = []
    for native_id, candidates in sorted(qnn_names.items()):
        if len(candidates) != 1:
            continue
        name = next(iter(candidates))
        names = sorted(sources.get(name, ()))
        if not names or any(len(onnx_nodes[source]) != 1 for source in names):
            continue
        mappings.append({
            "operation_ids": [native_id],
            "node_ids": [onnx_nodes[source][0] for source in names],
            "evidence": {"method": "QAIRT Optrace QNN Op Name → DLC framework trace → ONNX node name",
                         "qnn_op_name": name, "source_onnx_names": names, "framework_csv_sha256": fingerprint},
        })
    return mappings
