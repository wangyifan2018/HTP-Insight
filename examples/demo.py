import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import numpy as np
import torch

from htp_insight.core import Core, atomic_write, encode
from htp_insight.profiles import make_session, output_error

from .tiny import create_example, export, pack_qkv

from .downloads import RELEASE, fetch


def baseline(core):
    model, x = create_example()
    export(model, x, core.inbox / "tiny-baseline.onnx")
    np.savez(core.inbox / "tiny-input.npz", hidden=x.numpy())
    model_id = core.import_model("tiny-baseline.onnx", name="Tiny Transformer · Baseline")["artifact"]["id"]
    profile = core.run_ort_profile(model_id, "tiny-input.npz", warmup=50, repeats=500, trace_runs=8)
    return model, x, profile


def candidate(core, original, x, session, adapted):
    model_path = core.inbox / "tiny-candidate.onnx"
    export(adapted, x, model_path)
    with torch.inference_mode():
        before, after = original(x).numpy(), adapted(x).numpy()
    torch_check = output_error({"logits": before}, {"logits": after})
    for path, expected in ((core.inbox / "tiny-baseline.onnx", before), (model_path, after)):
        actual = make_session(path).run(None, {"hidden": x.numpy()})[0]
        verification = output_error({"logits": expected}, {"logits": actual})
        if not verification["passed"]:
            raise AssertionError(f"PyTorch and ONNX disagree for {path.name}: {verification}")
    model_id = core.import_model(model_path.name, name="Tiny Transformer · Packed QKV")["artifact"]["id"]
    adapted_session = core.run_ort_profile(model_id, "tiny-input.npz", warmup=50, repeats=500, trace_runs=8)
    explanation = core.explain_hotspot(session["id"], "attention")
    result = core.compare_experiments(session["id"], adapted_session["id"], explanation["hypothesis"]["adaptation"])
    return result, torch_check


def mobile(core, precision):
    url = f"{RELEASE}/mobilenet_v2-onnx-{precision}.zip"
    archive = core.root / "downloads" / f"{precision}.zip"
    fetch(url, archive)
    with ZipFile(archive) as package, TemporaryDirectory(dir=core.inbox) as folder:
        directory = Path(folder)
        eligible = {".onnx", ".data", ".bin", ".weights"}
        for item in package.infolist():
            target = (directory / item.filename).resolve()
            if not target.is_relative_to(directory) or item.file_size > 512 * 1024 * 1024:
                raise ValueError("Unexpected MobileNet package entry")
            if not item.is_dir() and (target.suffix in eligible or target.name.endswith(".onnx.data")):
                atomic_write(target, package.read(item))
        path, = directory.rglob("*.onnx")
        artifact = core.import_model(str(path.relative_to(core.inbox)), name=f"Qualcomm MobileNet-v2 · {precision}",
                                     origin=url)["artifact"]
    runner = make_session(core.item(artifact["id"], "model.onnx"))
    rng = np.random.default_rng(7)
    inputs = {}
    for item in runner.get_inputs():
        if not all(isinstance(d, int) for d in item.shape):
            raise ValueError(f"Unexpected MobileNet input: {item.type} {item.shape}")
        if item.type == "tensor(float)":
            inputs[item.name] = rng.random(item.shape, dtype=np.float32)
        elif item.type in {"tensor(uint8)", "tensor(uint16)"}:
            dtype = np.uint8 if item.type == "tensor(uint8)" else np.uint16
            inputs[item.name] = rng.integers(0, np.iinfo(dtype).max, endpoint=True, size=item.shape, dtype=dtype)
        else:
            raise ValueError(f"Unexpected MobileNet input dtype: {item.type}")
    input_file = f"mobilenet-{precision}-input.npz"
    np.savez(core.inbox / input_file, **inputs)
    result = core.run_ort_profile(artifact["id"], input_file, warmup=10, repeats=40, trace_runs=4)
    return {**result, "model": artifact, "quantization_entries": len(core.graph(artifact["id"]).quantization)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mobile-only", action="store_true")
    parser.add_argument("--tiny-only", action="store_true")
    args = parser.parse_args()
    core = Core()
    if not args.mobile_only:
        original, x, original_session = baseline(core)
        print("Baseline module ranking", [(row["module"], row["total_us"])
                                         for row in core.get_hotspots(original_session["id"])["hotspots"]], flush=True)
        result, check = candidate(core, original, x, original_session, pack_qkv(original))
        atomic_write(core.root / "demo.json", encode({**result, "pytorch_validation": check}))
        atomic_write(core.root / "report.md", core.report(result["id"]).encode())
        print(json.dumps({key: result[key] for key in ("id", "latency", "numeric", "deep_link")}, indent=2), flush=True)
        if not (check["passed"] and result["numeric"] and result["numeric"]["passed"]):
            raise SystemExit("Tiny Transformer output validation failed")
    if not args.tiny_only:
        mobile_results = []
        for precision in ("float", "w8a8", "w8a16"):
            result = mobile(core, precision)
            mobile_results.append(result)
            print(precision, result["id"], "QDQ entries", result["quantization_entries"],
                  "p50/p95 µs", result["latency_us"]["p50"], result["latency_us"]["p95"], flush=True)
        atomic_write(core.root / "mobile.json", encode(mobile_results))


if __name__ == "__main__":
    main()
