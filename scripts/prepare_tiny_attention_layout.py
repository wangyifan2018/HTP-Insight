"""Export and numerically verify the Tiny Transformer rank-3 score MatMul experiment."""

from copy import deepcopy
from math import sqrt
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import onnx
import torch

from examples.tiny import Attention, create_example, export
from htp_insight.core import Core, atomic_write, encode
from htp_insight.profiles import make_session, output_error


class FlatScoreAttention(Attention):
    def forward(self, x):
        b, t, _ = x.shape
        q, k, v = (layer(x).reshape(b, t, self.heads, self.head_width).transpose(1, 2)
                   for layer in (self.q, self.k, self.v))
        scores = q.reshape(b * self.heads, t, self.head_width) @ k.transpose(-1, -2).reshape(b * self.heads, self.head_width, t)
        scores = scores.reshape(b, self.heads, t, t)
        weights = torch.softmax(scores / sqrt(self.head_width), dim=-1)
        return self.out((weights @ v).transpose(1, 2).reshape(b, t, -1))


def expose_scores(path, destination):
    graph = onnx.shape_inference.infer_shapes(onnx.load(path))
    matmul = next(node for node in graph.graph.node if node.name == "/attention/MatMul")
    scaling = next(node for node in graph.graph.node if node.name == "/attention/Div")
    values = {value.name: value for value in graph.graph.value_info}
    score_name = scaling.input[0]
    graph.graph.output.append(values[score_name])
    onnx.save(graph, destination)
    ranks = [len(values[name].type.tensor_type.shape.dim) for name in matmul.input]
    return score_name, ranks


def main():
    core = Core()
    inbox = core.inbox / "tiny-attention-layout"
    inbox.mkdir(exist_ok=True)
    reference = core.root / "android-tiny" / "verification-inputs.npz"
    with np.load(reference, allow_pickle=False) as held_out:
        inputs = held_out["hidden"]
    baseline, example = create_example()
    candidate = deepcopy(baseline)
    candidate.attention = FlatScoreAttention(width=128, heads=4)
    candidate.attention.load_state_dict(baseline.attention.state_dict())
    candidate.eval()
    paths = [inbox / "baseline.onnx", inbox / "flat-score.onnx"]
    for model, path in zip((baseline, candidate), paths):
        export(model, example, path)
    checks = []
    with TemporaryDirectory() as temporary:
        diagnostic_paths = [Path(temporary) / path.name for path in paths]
        outputs, ranks = zip(*(expose_scores(path, diagnostic)
                               for path, diagnostic in zip(paths, diagnostic_paths)))
        if ranks != ([4, 4], [3, 3]):
            raise ValueError(f"Expected rank-4 baseline and rank-3 candidate score inputs, got {ranks}")
        sessions = [make_session(path) for path in diagnostic_paths]
        for sample in inputs:
            with torch.inference_mode():
                eager = [model(torch.from_numpy(sample)).numpy() for model in (baseline, candidate)]
            left, right = [session.run([score, "logits"], {"hidden": sample})
                           for session, score in zip(sessions, outputs)]
            checks.append({
                "ort_scores": output_error({"scores": left[0]}, {"scores": right[0]}),
                "ort_logits": output_error({"logits": left[1]}, {"logits": right[1]}),
                "eager_logits": output_error({"logits": eager[0]}, {"logits": eager[1]}),
                "baseline_export": output_error({"logits": eager[0]}, {"logits": left[1]}),
                "candidate_export": output_error({"logits": eager[1]}, {"logits": right[1]}),
            })
    if not all(check["passed"] for sample in checks for check in sample.values()):
        raise ValueError("Rank-3 layout did not preserve FP32 outputs")
    result = {"fp32": checks, "score_node": "/attention/MatMul",
              "input_ranks": {"baseline": ranks[0], "candidate": ranks[1]},
              "models": [core.import_model(str(path.relative_to(core.inbox)), name=name)["artifact"]
                         for path, name in zip(paths, ("Tiny Transformer · Layout Baseline", "Tiny Transformer · Rank-3 Scores"))]}
    atomic_write(core.root / "tiny-attention-layout-fp32.json", encode(result))
    print(core.root / "tiny-attention-layout-fp32.json")


if __name__ == "__main__":
    main()
