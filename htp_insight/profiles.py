import hashlib
import json
import math
import platform
import re
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path
from time import perf_counter_ns
from typing import Protocol

import numpy as np
import onnxruntime as ort

from .qnn_csv import QnnViewerCsvAdapter
from .schema import Graph, NodeMapping, ProfileEvent, ProfileSession, Source


class ProfileAdapter(Protocol):
    source: Source

    def parse(self, raw: bytes, session: ProfileSession, graph: Graph) -> None: ...


class QnnNativeRunner(Protocol):
    def run(self, artifact_id: str, inputs: Path, conditions: dict) -> ProfileSession: ...


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def chrome_events(raw):
    document = json.loads(raw)
    rows = document.get("traceEvents") if isinstance(document, dict) else document
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Expected a Chrome Trace event array or traceEvents object")
    for index, row in enumerate(rows):
        if row.get("ph") != "X":
            continue
        name, start, duration = row.get("name"), row.get("ts"), row.get("dur")
        if not isinstance(name, str) or not finite_number(start) or not finite_number(duration) or duration < 0:
            raise ValueError(f"Invalid complete trace event at index {index}")
        args = row.get("args", {})
        if not isinstance(args, dict):
            raise ValueError(f"Invalid trace args at index {index}")
        yield index, row, name, start, duration, args


class ChromeTraceAdapter:
    def __init__(self, source: Source):
        self.source = source

    def parse(self, raw, session, graph):
        names = defaultdict(list)
        for node in graph.nodes:
            names[(node.name, node.op)].append(node.id)
        events = []
        operations = {}
        for index, row, name, start, duration, args in chrome_events(raw):
            track = f'{row.get("pid", "?")} / {row.get("tid", "?")}'
            operation = None
            if self.source == "ORT":
                if row.get("cat") == "Node" and name.endswith("_kernel_time"):
                    node_name = name.removesuffix("_kernel_time")
                    op = args.get("op_name")
                    operation = f"{node_name} [{op}]"
                    matches = names[(node_name, op)] if isinstance(op, str) else []
                    operations[operation] = NodeMapping(
                        operation_ids=[operation], node_ids=matches if len(matches) == 1 else [],
                        method="exact-name-op" if len(matches) == 1 else "unknown",
                    )
                    kind = "node"
                elif row.get("cat") == "Session" and name == "model_run":
                    kind = "inference"
                else:
                    continue
            else:
                kind = "node"
                operation = str(args.get("operation_id", name))
                operations[operation] = NodeMapping(operation_ids=[operation], node_ids=[], method="unknown")
            events.append(ProfileEvent(
                id=f"{session.id}-e{index}", source=self.source,
                backend=args.get("provider") if isinstance(args.get("provider"), str) else session.backend,
                profiler_version=session.profiler_version, device=session.device,
                operation=operation, name=name, kind=kind, start=start, duration=duration, track=track,
                resource=args.get("resource") if isinstance(args.get("resource"), str) else None,
                raw_index=index,
            ))
        if not any(event.kind == "node" for event in events):
            raise ValueError(f"No supported {self.source} operation events found")
        events.sort(key=lambda event: (event.start, event.raw_index))
        if self.source == "ORT":
            runs = [event for event in events if event.kind == "inference"]
            starts = [event.start for event in runs]
            for event in events:
                if event.kind == "node":
                    parent_index = bisect_right(starts, event.start) - 1
                    if parent_index >= 0:
                        parent = runs[parent_index]
                        if event.start + event.duration <= parent.start + parent.duration:
                            event.parent = parent.id
        session.events = events
        session.mappings = list(operations.values())


class QnnLintingTraceAdapter:
    """Chrome Trace emitted by the QAIRT 2.50 HTP linting reader, in DSP cycles."""

    source = "QNN"
    operation_id = re.compile(r"\b(OpId_\d+) \(cycles\)$")

    def parse(self, raw, session, graph):
        operations = set()
        events = []
        for index, row, name, start, duration, args in chrome_events(raw):
            track = row.get("tid")
            match = self.operation_id.search(name) if track == "Foreground" else None
            operation = match.group(1) if match else None
            if operation:
                operations.add(operation)
                kind = "node"
            elif track == "Foreground" and name == "Wait":
                kind = "wait"
            elif track == "Background" and duration:
                kind = "overlap"
            else:
                continue
            resource = args.get("Resources")
            events.append(ProfileEvent(
                id=f"{session.id}-e{index}", source=self.source, backend=session.backend,
                profiler_version=session.profiler_version, device=session.device, kind=kind, name=name,
                start=start, duration=duration, unit="cycles", track=track, operation=operation,
                resource=resource if isinstance(resource, str) else None, raw_index=index,
            ))
        if not operations:
            raise ValueError("Expected QAIRT 2.50 linting Foreground operations in DSP cycles")
        session.unit = "cycles"
        session.events = sorted(events, key=lambda event: (event.start, event.raw_index))
        session.mappings = [NodeMapping(operation_ids=[op], node_ids=[], method="unknown") for op in sorted(operations)]



class QnnOptraceAdapter:
    """Device Optrace from QAIRT 2.50, with one event per measured HTP operation."""

    source = "Optrace"

    def parse(self, raw, session, graph):
        document = json.loads(raw)
        header = document.get("header") if isinstance(document, dict) else None
        if not isinstance(header, dict) or header.get("artifact_type") != "OP_TRACE":
            raise ValueError("Expected a QAIRT 2.50 OP_TRACE artifact")

        track_labels = {}
        for row in document.get("traceEvents", []):
            if isinstance(row, dict) and row.get("ph") == "M" and row.get("name") == "thread_name":
                args = row.get("args")
                if isinstance(args, dict) and isinstance(args.get("name"), str):
                    track_labels[(str(row.get("pid")), str(row.get("tid")))] = args["name"]

        seen = set()
        operations = set()
        events = []
        for index, row, name, start, duration, args in chrome_events(raw):
            if "HTP Op Type" not in args or "Duration (cycles)" not in args:
                continue
            operation, absolute_start = args.get("ID"), args.get("Start Cycle")
            if not isinstance(operation, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", operation):
                raise ValueError(f"Invalid HTP operation ID at trace index {index}")
            if not finite_number(absolute_start) or args["Duration (cycles)"] != duration:
                raise ValueError(f"Invalid QAIRT Optrace cycle data at trace index {index}")
            identity = (operation, absolute_start, duration)
            if identity in seen:
                continue
            seen.add(identity)
            operations.add(operation)
            pid, tid = str(row.get("pid")), str(row.get("tid"))
            flags = args.get("Flags", [])
            if not isinstance(flags, list):
                raise ValueError(f"Invalid QAIRT Optrace flags at trace index {index}")
            resource = [label for label, keys in (
                ("HMX", {"uses_hmx"}), ("HVX", {"uses_hvx"}), ("DMA", {"dma", "dma_set", "dma_wait"}),
            ) if any(isinstance(flag, str) and flag in keys for flag in flags)]
            events.append(ProfileEvent(
                id=f"{session.id}-e{index}", source=self.source, backend=session.backend,
                profiler_version=session.profiler_version, device=session.device, kind="node", name=name,
                start=start, duration=duration, unit="cycles", track=track_labels.get((pid, tid), f"HTP track {tid}"),
                operation=operation, resource=", ".join(resource) if resource else None, raw_index=index,
            ))
        if not events:
            raise ValueError("No measured HTP operations with cycle durations")
        session.unit = "cycles"
        session.events = sorted(events, key=lambda event: (event.start, event.raw_index))
        session.mappings = [NodeMapping(operation_ids=[op], node_ids=[], method="unknown") for op in sorted(operations)]



ADAPTERS: dict[str, ProfileAdapter] = {
    "qnn-viewer-csv-v2.50": QnnViewerCsvAdapter(),
    "ort-chrome-v1": ChromeTraceAdapter("ORT"),
    "optrace-chrome-v1": ChromeTraceAdapter("Optrace"),
    "qnn-linting-chrome-v2.50": QnnLintingTraceAdapter(),
    "qnn-optrace-chrome-v2.50": QnnOptraceAdapter(),
}


def make_session(model, profiling=False, prefix=None):
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    options.enable_profiling = profiling
    if prefix is not None:
        options.profile_file_prefix = str(prefix)
    return ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])


def output_error(reference, actual, atol=1e-5, rtol=1e-4):
    if reference.keys() != actual.keys():
        raise ValueError("Output names differ")
    if not reference:
        raise ValueError("No outputs")
    results = {}
    for name, expected in reference.items():
        value = actual[name]
        if expected.shape != value.shape or expected.dtype != value.dtype:
            raise ValueError(f"Output shape or dtype differs for {name}")
        if np.issubdtype(expected.dtype, np.number) and not np.issubdtype(expected.dtype, np.complexfloating):
            if not np.isfinite(expected).all() or not np.isfinite(value).all():
                raise ValueError(f"Nonfinite output for {name}")
            if np.issubdtype(expected.dtype, np.integer):
                # Unsigned subtraction preserves differences across signed int64 endpoints.
                a, b = expected.astype(np.uint64), value.astype(np.uint64)
                error = np.where(expected >= value, a - b, b - a)
                maximum = int(error.max(initial=0))
                equal = np.array_equal(expected, value)
            else:
                error = np.abs(expected.astype(np.float64) - value.astype(np.float64))
                maximum = float(error.max(initial=0))
                equal = np.allclose(value, expected, atol=atol, rtol=rtol)
            results[name] = {"shape": list(value.shape), "dtype": str(value.dtype),
                             "max_abs": maximum, "mean_abs": float(error.mean()) if error.size else None,
                             "allclose": bool(equal)}
        else:
            results[name] = {"shape": list(value.shape), "dtype": str(value.dtype),
                             "max_abs": None, "mean_abs": None, "allclose": bool(np.array_equal(expected, value))}
    return {"atol": atol, "rtol": rtol, "passed": all(x["allclose"] for x in results.values()), "outputs": results}


def input_digest(inputs):
    digest = hashlib.sha256()
    for key, array in sorted(inputs.items()):
        digest.update(json.dumps([key, array.shape, array.dtype.str]).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def benchmark(model: Path, inputs_path: Path, work: Path, warmup: int, repeats: int, trace_runs: int):
    if not (1 <= warmup <= 100 and 2 <= repeats <= 1000 and 1 <= trace_runs <= 20):
        raise ValueError("Expected warmup 1–100, repeats 2–1000, trace_runs 1–20")
    with np.load(inputs_path, allow_pickle=False) as payload:
        inputs = {key: payload[key] for key in payload.files}
    session = make_session(model)
    names = [item.name for item in session.get_outputs()]
    for _ in range(warmup):
        output = session.run(None, inputs)
    reference = dict(zip(names, output))
    output_error(reference, reference)
    samples = []
    for _ in range(repeats):
        start = perf_counter_ns()
        output = session.run(None, inputs)
        samples.append((perf_counter_ns() - start) / 1000)
    actual = dict(zip(names, output))
    if not output_error(reference, actual)["passed"]:
        raise ValueError("Repeated inference output differs from warmup output")

    trace_session = make_session(model, True, work / "ort")
    try:
        for _ in range(trace_runs):
            trace_output = trace_session.run(None, inputs)
    finally:
        raw = Path(trace_session.end_profiling()).read_bytes()
    if not output_error(actual, dict(zip(names, trace_output)))["passed"]:
        raise ValueError("Instrumented inference output differs from uninstrumented output")
    np.savez(work / "outputs.npz", **actual)
    latency = {"p50": float(np.percentile(samples, 50)), "p95": float(np.percentile(samples, 95)),
               "samples": samples, "scope": "perf_counter_ns around uninstrumented session.run"}
    conditions = {
        "warmup": warmup, "repeats": repeats, "trace_runs": trace_runs, "intra_op_threads": 1,
        "inter_op_threads": 1, "execution_mode": "sequential", "graph_optimization": "ORT_DISABLE_ALL",
        "profiling_level": "ORT node trace", "input_sha256": input_digest(inputs),
        "inputs": {k: {"shape": list(v.shape), "dtype": str(v.dtype)} for k, v in inputs.items()},
        "soc": platform.processor() or None, "compile_parameters": None, "output_validation": "repeat and trace allclose",
    }
    return raw, latency, conditions, ort.__version__
