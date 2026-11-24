"""Measure the fixed Tiny Transformer rank-3 score experiment with paired Android captures."""

import argparse
import json
import re
from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace

import numpy as np

from htp_insight.android import AndroidRunner
from htp_insight.core import Core, atomic_write, encode
from htp_insight.profiles import make_session, output_error


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--adb", default=str(Path.home() / "Library/Android/sdk/platform-tools/adb"))
    cli.add_argument("--serial")
    cli.add_argument("--sdk", required=True, type=Path)
    args = cli.parse_args()
    core = Core()
    runner = AndroidRunner(args.adb, args.serial, args.sdk, "v73", 120)
    folder = core.root / "attention-score-layout"
    originals = core.root / "android-tiny"
    models = [row["id"] for row in json.loads((core.root / "tiny-attention-layout-fp32.json").read_bytes())["models"]]
    dlcs = [originals / "baseline/aimet-w8a16.dlc", folder / "flat-score.dlc"]

    def capture(index, sample, runs, warmup):
        spec = SimpleNamespace(model_id=models[index], model=dlcs[index], input=[f"hidden={sample}"], mode="basic",
                               runs=runs, warmup=warmup, native_io=False, perf_profile="default",
                               keep_device_files=False, schematic=None, trace_dlc=None, framework_csv=None)
        return runner.capture(core, spec)

    sessions = [make_session(core.item(identifier, "model.onnx")) for identifier in models]
    validation = []
    for sample in sorted((originals / "inputs").glob("hidden-*.raw")):
        expected = np.fromfile(sample, dtype="<f4").reshape(1, 12, 64)
        captures = [capture(index, sample, 1, 0) for index in (0, 1)]
        outputs = []
        for data in captures:
            output, = (Path(data["capture"]) / "Result_0").glob("*.raw")
            outputs.append(np.fromfile(output, dtype="<f4").reshape(1, 12, 64))
        references = [session.run(["logits"], {"hidden": expected})[0] for session in sessions]
        checks = [output_error({"logits": a}, {"logits": b}, atol=.03, rtol=.03)
                  for a, b in [(outputs[0], outputs[1]), *zip(references, outputs)]]
        validation.append({"sample": sample.name, "profiles": [row["profile"]["id"] for row in captures], "checks": checks})
    if len(validation) != 8:
        raise ValueError("Expected eight held-out inputs")
    atomic_write(folder / "numeric.json", encode(validation))
    print("Device numeric captures complete", flush=True)

    def battery_celsius():
        try:
            probe = runner.shell(["dumpsys", "battery"])
        except (RuntimeError, OSError, TimeoutExpired):
            return None
        match = re.search(r"^\s*temperature:\s*(-?\d+)\s*$", probe, re.MULTILINE)
        return int(match.group(1)) / 10 if match else None

    temperature_celsius = {}

    def paired(variants):
        captures = []
        for index in variants:
            before = battery_celsius()
            profile = capture(index, originals / "inputs/hidden-0.raw", 110, 10)["profile"]
            temperature_celsius[profile["id"]] = {"before": before, "after": battery_celsius()}
            captures.append(profile)
        if variants == (1, 0):
            captures.reverse()
        return captures

    aa = [paired((0, 0)) for _ in range(3)]
    ab = []
    for block in range(6):
        ab.append(paired((0, 1) if block % 2 == 0 else (1, 0)))
        print(f"Recorded A/B block {block + 1}", flush=True)

    def gap(left, right):
        return (right / left - 1) * 100

    aa_p50 = max(abs(gap(left["latency_us"]["p50"], right["latency_us"]["p50"])) for left, right in aa)
    aa_p95 = max(abs(gap(left["latency_us"]["p95"], right["latency_us"]["p95"])) for left, right in aa)
    pooled = [[sample for block in ab for sample in block[index]["latency_us"]["samples"]] for index in (0, 1)]
    percentiles = [np.percentile(samples, [50, 95]).tolist() for samples in pooled]
    p50, p95 = [gap(left, right) for left, right in zip(*percentiles)]
    wins = sum(b["latency_us"]["p50"] < a["latency_us"]["p50"] for a, b in ab)
    numeric = all(check["passed"] for sample in validation for check in sample["checks"])
    passed = numeric and p50 <= -5 and abs(p50) > aa_p50 and p95 <= 2 and aa_p95 <= 2 and wins >= 5
    comparisons = [core.compare_experiments(left["id"], right["id"], "Rank-3 score MatMul on the same SM6650 workload",
                                            atol=.03, rtol=.03, name=f"Tiny rank-3 score · Paired block {i}")
                   for i, (left, right) in enumerate(ab, 1)]
    comparison_issues = {row["id"]: row["latency"]["comparison_issues"] for row in comparisons
                         if not row["latency"]["comparable"]}
    result = {"aa": aa, "ab": ab, "experiments": [row["id"] for row in comparisons],
              "battery_temperature_celsius": temperature_celsius, "comparison_issues": comparison_issues,
              "percentiles_us": percentiles, "delta_pct": None if comparison_issues else {"p50": p50, "p95": p95},
              "aa_max_delta_pct": {"p50": aa_p50, "p95": aa_p95}, "wins_p50": wins,
              "numeric_passed": numeric, "performance_passed": passed and not comparison_issues}
    target = folder / "paired-results.json"
    atomic_write(target, encode(result))
    print(target)


if __name__ == "__main__":
    main()
