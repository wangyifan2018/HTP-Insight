"""Extract the pinned Code Predictor's first MLP and validate it against the full ONNX graph."""

from argparse import ArgumentParser
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import onnx

from htp_insight.core import Core, atomic_write, encode
from htp_insight.profiles import make_session, output_error

INPUT = "/model/layers.0/post_attention_layernorm/Mul_1_output_0"
OUTPUT = "/model/layers.0/mlp/down_proj/MatMul_output_0"
SHAPE = (1, 1, 1024)


def extract(source: Path, target: Path):
    graph = onnx.shape_inference.infer_shapes(onnx.load(source))
    mlp = onnx.utils.Extractor(graph).extract_model([INPUT], [OUTPUT])
    for tensor in (*mlp.graph.input, *mlp.graph.output):
        for dimension, length in zip(tensor.type.tensor_type.shape.dim, SHAPE):
            dimension.dim_value = length
    atomic_write(target, mlp.SerializeToString())


def main():
    core = Core()
    parent = core.inbox / "qwen3-tts-0.6b"
    source = parent / "code_predictor.onnx"
    weights = parent / "layer0/mlp.onnx"
    work = core.root / "qwen3-tts-0.6b/layer0-mlp"
    work.mkdir(parents=True, exist_ok=True)
    extract(source, weights)
    instrumented = onnx.load(source, load_external_data=False)
    instrumented.graph.output.extend(onnx.helper.make_tensor_value_info(name, onnx.TensorProto.FLOAT, [1, "tokens", 1024])
                                     for name in (INPUT, OUTPUT))
    with NamedTemporaryFile(suffix=".onnx", dir=parent) as probe:
        probe.write(instrumented.SerializeToString())
        probe.flush()
        full = make_session(Path(probe.name))
        with np.load(parent / "decode-step-1.npz", allow_pickle=False) as decode:
            x, expected = full.run([INPUT, OUTPUT], dict(decode.items()))
        actual = make_session(weights).run([OUTPUT], {INPUT: x})[0]
        numeric = output_error({OUTPUT: expected}, {OUTPUT: actual})
        if not numeric["passed"]:
            raise ValueError("Extracted MLP output differs from the full ONNX graph")
        empty = np.empty((5, 1, 8, 0, 128), dtype=np.float32)
        rng = np.random.default_rng(97)
        for i in range(8):
            keys, values = full.run(["present_keys", "present_values"], {
                "inputs_embeds": rng.normal(0, .1, (1, 2, 1024)).astype(np.float32),
                "generation_steps": np.array([0], np.int64), "past_keys": empty, "past_values": empty,
            })
            hidden, = full.run([INPUT], {
                "inputs_embeds": rng.normal(0, .1, SHAPE).astype(np.float32),
                "generation_steps": np.array([1], np.int64), "past_keys": keys, "past_values": values,
            })
            np.save(work / f"calibration-{i}.npy", hidden)
    atomic_write(work / "validation-input.raw", x.tobytes())
    atomic_write(work / "reference-output.raw", expected.tobytes())
    atomic_write(work / "mlp.onnx", weights.read_bytes())
    sample = BytesIO()
    np.savez(sample, **{INPUT: x})
    atomic_write(weights.parent / "benchmark.npz", sample.getvalue())
    artifact = core.import_model(str(weights.relative_to(core.inbox)), name="Qwen3-TTS Code Predictor · Layer 0 MLP")["artifact"]
    profile = core.run_ort_profile(artifact["id"], "qwen3-tts-0.6b/layer0/benchmark.npz", warmup=5, repeats=30, trace_runs=3)
    atomic_write(work / "cpu.json", encode({"artifact": artifact, "profile": profile, "against_full_model": numeric,
                                           "input": INPUT, "output": OUTPUT}))
    print(profile["deep_link"])


if __name__ == "__main__":
    ArgumentParser(description=__doc__).parse_args()
    main()
