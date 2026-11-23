"""Calibrate the demo's Tiny Transformer with the optional AIMET 2.44 environment."""
import argparse
import os
from pathlib import Path

import numpy as np
import onnx
from aimet_onnx import QuantizationSimModel


def main():
    root = Path(__file__).resolve().parents[1]
    inbox = Path(os.getenv("HTP_INSIGHT_DATA", root / "runs")) / "inbox"
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", type=Path, default=inbox)
    args = parser.parse_args()
    with np.load(args.inbox / "tiny-input.npz", allow_pickle=False) as package:
        example_input = package["hidden"]
    sim = QuantizationSimModel(
        onnx.load(args.inbox / "tiny-baseline.onnx"),
        providers=["CPUExecutionProvider"],
        dummy_input={"hidden": example_input},
        param_type="int8",
        activation_type="int8",
        session_options_kwargs={"intra_op_num_threads": 1, "inter_op_num_threads": 1},
    )
    rng = np.random.default_rng(7)
    samples = [{"hidden": rng.standard_normal(example_input.shape, dtype=np.float32)} for _ in range(32)]
    sim.compute_encodings(samples)
    logits = sim.session.run(None, {"hidden": example_input})[0]
    if not np.isfinite(logits).all():
        raise ValueError("AIMET calibration produced nonfinite logits")
    sim.export(str(args.inbox), "tiny-aimet", encoding_version="2.0.0")
    print(args.inbox / "tiny-aimet.encodings")


if __name__ == "__main__":
    main()
