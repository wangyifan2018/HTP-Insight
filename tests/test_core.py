import json
from pathlib import Path

import numpy as np
import onnx
import pytest
from onnx import TensorProto as T, helper as h

from htp_insight.core import Core
from htp_insight.profiles import output_error


@pytest.fixture
def local(tmp_path):
    core = Core(tmp_path)
    # Explicit test fixture graph with deterministic names and an actual QDQ round trip.
    model = h.make_model(h.make_graph([
        h.make_node("QuantizeLinear", ["x", "scale", "zero"], ["qx"], name="quant"),
        h.make_node("DequantizeLinear", ["qx", "scale", "zero"], ["y"], name="dequant"),
    ], "qdq_test", [h.make_tensor_value_info("x", T.FLOAT, [1, 2])],
        [h.make_tensor_value_info("y", T.FLOAT, [1, 2])],
        [h.make_tensor("scale", T.FLOAT, [], [.25]), h.make_tensor("zero", T.UINT8, [], [0])]),
        opset_imports=[h.make_opsetid("", 17)])
    onnx.save(model, core.inbox / "test.onnx")
    np.savez(core.inbox / "test.npz", x=np.array([[.5, 1.25]], np.float32))
    artifact = core.import_model("test.onnx")["artifact"]
    return core, artifact["id"]


def test_model_and_qdq(local):
    core, model_id = local
    graph = core.graph(model_id)
    assert graph.initializer_elements == 2
    assert graph.tensors["qx"].dtype == "UINT8"
    assert graph.tensors["y"].shape == [1, 2]
    assert graph.nodes[1].predecessors == ["n0"]
    assert [record.operation for record in graph.quantization] == ["QuantizeLinear", "DequantizeLinear"]
    assert graph.quantization[1].scale == [.25]
    assert graph.quantization[1].zero_point == [0]
    assert core.import_model("test.onnx")["artifact"]["id"] == model_id
    with pytest.raises(ValueError, match="under the inbox"):
        core.import_model("../test.onnx")


def test_scoped_transformer_modules(local):
    core, _ = local
    model = h.make_model(h.make_graph([
        h.make_node("Identity", ["x"], ["a"], name="/model/layers.0/self_attn/Identity"),
        h.make_node("Identity", ["a"], ["b"], name="/model/layers.1/self_attn/Identity"),
        h.make_node("Identity", ["b"], ["y"], name="/model/layers.1/mlp/Identity"),
    ], "scoped", [h.make_tensor_value_info("x", T.FLOAT, [1, 2])],
        [h.make_tensor_value_info("y", T.FLOAT, [1, 2])]))
    onnx.save(model, core.inbox / "scoped.onnx")
    graph = core.graph(core.import_model("scoped.onnx")["artifact"]["id"])
    assert graph.architecture == "Transformer"
    assert [(module.id, module.parent) for module in graph.modules] == [
        ("layer.0.attention", "layer.0"), ("layer.1.attention", "layer.1"), ("layer.1.mlp", "layer.1"),
    ]


def test_htp_timeline_requires_recorded_flow_for_possible_blocker(local):
    core, model_id = local

    def timed(identifier, tid, start, duration, flags, **args):
        return {"ph": "X", "pid": 0, "tid": tid, "name": identifier, "ts": start, "dur": duration,
                "args": {"ID": identifier, "HTP Op Type": identifier, "Start Cycle": 1000 + start,
                         "Duration (cycles)": duration, "Flags": flags, **args}}

    def flow(phase, identifier, tid, time):
        return {"ph": phase, "cat": "sequencer", "pid": 0, "id": identifier, "tid": tid, "ts": time}

    rows = [
        {"ph": "M", "pid": 0, "name": "process_name", "args": {"name": "Core 0 Overview"}},
        {"ph": "M", "pid": 0, "tid": 256, "name": "thread_name", "args": {"name": "Type: HMX"}},
        {"ph": "M", "pid": 0, "tid": 513, "name": "thread_name", "args": {"name": "Type: HLX"}},
        timed("0x1", 256, 0, 30, ["uses_hmx"]),
        timed("0x2", 513, 20, 80, ["uses_hlx"]),
        timed("0x3", 256, 104, 26, ["uses_hmx"], **{"Inputs Ops": ["0x0002"]}),
        timed("0x4", 256, 130, 10, ["dma_wait"]),
        flow("s", 1, 513, 100), flow("f", 1, 256, 104),
        flow("s", 2, 513, 99), flow("f", 2, 256, 104),
    ]
    trace = core.inbox / "lanes.json"
    trace.write_text(json.dumps({"header": {"artifact_type": "OP_TRACE"}, "traceEvents": rows}))
    profile = core.import_profile(model_id, trace.name, "qnn-optrace-chrome-v2.50", fixture=True)
    result = core.inspect_htp_timeline(profile["id"])
    assert result["provenance"] == "fixture"
    assert [(lane["type"], lane["tid"]) for lane in result["lanes"]] == [("HMX", 256), ("HLX", 513)]
    assert result["unresolved_flow_count"] == 1
    assert len(result["dependencies"]) == 1
    assert {row["kind"] for row in result["dependencies"][0]["evidence"]} == {"trace_sequencer", "trace_input"}
    assert len(result["waits"]) == len(result["blockers"]) == 1
    assert result["waits"][0]["cycles"] == 10
    blocker, = result["blockers"]
    assert result["events"][blocker["source"]]["operation_id"] == "0x2"
    assert blocker["overlap_cycles"] == 70 and blocker["after_producer_cycles"] == 4

    trace.write_text(json.dumps({"header": {"artifact_type": "OP_TRACE"}, "traceEvents": rows[:-4]}))
    profile = core.import_profile(model_id, trace.name, "qnn-optrace-chrome-v2.50", fixture=True)
    assert core.inspect_htp_timeline(profile["id"])["blockers"] == []


@pytest.mark.parametrize("records", [
    {"x": [{"bitwidth": 8, "dtype": "int", "scale": .25}]},
    [{"name": "x", "bw": 8, "dtype": "INT", "scale": [.25]}],
    [{"name": "x", "output_dtype": "uint8", "y_scale": .25, "y_zero_point": 0}],
])
def test_encodings(local, records):
    core, _ = local
    filename = core.inbox / "fixture.encodings"
    filename.write_text(json.dumps({"activation_encodings": records}))
    identifier = core.import_model("test.onnx", encodings=filename.name)["artifact"]["id"]
    model = core.graph(identifier)
    assert model.quantization[0].format == "AIMET"
    assert model.quantization[0].bitwidth == 8
    assert model.quantization[0].scale == [.25]
    assert 0 in model.nodes[0].quantization


def fixture_profile(core, identifier):
    raw = Path("tests/fixtures/optrace-chrome.json").read_bytes()
    mappings = [
        {"operation_ids": ["fixture_operation_A"], "node_ids": ["n0", "n1"]},
        {"operation_ids": ["fixture_operation_A", "fixture_operation_B"], "node_ids": ["n1"]},
    ]
    (core.inbox / "fixture.json").write_bytes(raw)
    (core.inbox / "mapping.json").write_text(json.dumps(mappings))
    return core.import_profile(identifier, "fixture.json", "optrace-chrome-v1", True, mapping_file="mapping.json")


def test_optrace_mapping_and_ranking(local):
    core, identifier = local
    session = fixture_profile(core, identifier)
    assert session["provenance"] == "fixture"
    ranked = core.get_hotspots(session["id"], "node")["hotspots"]
    assert [item["total_us"] for item in ranked] == [9, 3, 2]
    assert ranked[0]["node_ids"] == ["n0", "n1"]
    assert ranked[0]["share"] == 9 / 14
    assert ranked[-1]["module"] == "Unknown"
    assert all(item["scope"] for item in ranked)
    explanation = core.explain_hotspot(session["id"], ranked[0]["id"], "node")
    assert explanation["example_evidence"]["raw_index"] == 1
    assert explanation["hypothesis"]["kind"] == "hypothesis"
    assert explanation["nodes"][0]["output_tensors"][0]["dtype"] == "UINT8"
    assert core.suggest_experiments(session["id"])["suggestions"]


@pytest.mark.parametrize("content", [b"{}", b'[{"ph":"X","name":"broken","ts":1,"dur":-1}]', b"[]", b"not JSON"])
def test_malformed_profile(local, content):
    core, identifier = local
    (core.inbox / "invalid.json").write_bytes(content)
    with pytest.raises(ValueError):
        core.import_profile(identifier, "invalid.json", "optrace-chrome-v1")
    with pytest.raises(ValueError, match="Future Integration"):
        core.import_profile(identifier, "invalid.json", "qhas-json")
    assert core.catalog()["profiles"] == []


def test_measured_trace_and_comparison(local):
    core, identifier = local
    a = core.run_ort_profile(identifier, "test.npz", 2, 5, 2)
    b = core.run_ort_profile(identifier, "test.npz", 2, 5, 2)
    assert a["latency_us"]["p95"] > 0
    parsed = core.profile(a["id"])
    assert len(parsed["events"]) == 6
    assert all(event["parent"] for event in parsed["events"] if event["kind"] == "node")
    assert {item["method"] for item in parsed["mappings"]} == {"exact-name-op"}
    report = core.compare_experiments(a["id"], b["id"])
    assert report["latency"]["comparable"]
    assert report["numeric"]["passed"]
    assert report["graph_diff"]["operator_changes"] == []
    assert report["graph_diff"]["edges_added"] == report["graph_diff"]["edges_removed"] == []
    assert "Numerical validation" in core.report(report["id"])
    fixture = fixture_profile(core, identifier)
    unmatched = core.compare_experiments(a["id"], fixture["id"])
    assert unmatched["numeric"] is None
    assert unmatched["latency"]["p50"]["delta_pct"] is None


def test_output_mismatch_and_htp_artifact(local):
    core, _ = local
    report = output_error({"y": np.array([1.])}, {"y": np.array([2.])})
    assert not report["passed"]
    assert report["outputs"]["y"]["max_abs"] == 1
    bounds = np.iinfo(np.int64)
    exact = output_error({"y": np.array([bounds.min])}, {"y": np.array([bounds.max])})
    assert exact["outputs"]["y"]["max_abs"] == 2**64 - 1
    (core.inbox / "fixture.bin").write_bytes(b"fixture context bytes")
    details = core.import_model("fixture.bin", target_device="Fixture SoC", compatibility={"sdk":"fixture"})["artifact"]
    assert details["format"] == "HTP_CONTEXT"
    assert len(details["sha256"]) == 64
    assert details["target_device"] == "Fixture SoC"
    with pytest.raises(ValueError, match="ONNX model"):
        core.run_ort_profile(details["id"], "test.npz")


def test_real_qnn_linting_excerpt(local):
    core, identifier = local
    (core.inbox / "linting.json").write_bytes(Path("tests/fixtures/qnn-linting-2.50.json").read_bytes())
    result = core.import_profile(identifier, "linting.json", "qnn-linting-chrome-v2.50", fixture=True,
                                 backend="QNN HTP", profiler_version="v2.50.40.260831140417")
    assert result["source"] == "QNN"
    assert result["unit"] == "cycles"
    profile = core.profile(result["id"])
    assert {entry["kind"] for entry in profile["events"]} == {"node", "wait", "overlap"}
    assert not any(mapping["node_ids"] for mapping in profile["mappings"])
    ranked = core.get_hotspots(result["id"], "node")["hotspots"]
    assert ranked[0]["id"] == "OpId_17"
    assert ranked[0]["total_cycles"] == 153248
    assert ranked[0]["total_us"] is None
    assert ranked[0]["share"] == 153248 / (153248 + 3032 + 106148)
    explanation = core.explain_hotspot(result["id"], "OpId_17", "node")
    assert explanation["example_evidence"]["resource"] == "HVX, DMA"
    assert explanation["unit"] == "cycles"
    (core.inbox / "wrong.json").write_bytes(Path("tests/fixtures/optrace-chrome.json").read_bytes())
    with pytest.raises(ValueError, match="linting Foreground"):
        core.import_profile(identifier, "wrong.json", "qnn-linting-chrome-v2.50")


def test_real_qnn_optrace_deduplicates_and_joins_framework_trace(local):
    core, model_id = local
    trace = json.loads(Path("tests/fixtures/qnn-optrace-2.50.json").read_text())
    original = trace["traceEvents"][0]
    (core.inbox / "optrace.json").write_text(json.dumps(trace))
    (core.inbox / "dlc.csv").write_text(
        "QAIRT DLC table fixture\n"
        "Current name,Current type,Source name,Source type\n"
        "/attention/MatMul,OP,quant,OP\n"
        ",,dequant,OP\n"
        ",,/tensor,TENSOR\n\n"
    )
    profile = core.import_profile(model_id, "optrace.json", "qnn-optrace-chrome-v2.50",
                                  fixture=True, framework_csv="dlc.csv")
    assert profile["event_count"] == 1
    assert profile["unit"] == "cycles"
    evidence = core.profile(profile["id"])
    assert evidence["mappings"][0]["operation_ids"] == [original["args"]["ID"]]
    assert set(evidence["mappings"][0]["node_ids"]) == {"n0", "n1"}
    assert evidence["mappings"][0]["evidence"]["qnn_op_name"] == "/attention/MatMul"
    ranking = core.get_hotspots(profile["id"], "node")["hotspots"]
    assert ranking[0]["total_cycles"] == original["dur"]
    assert ranking[0]["share"] == 1
    explanation = core.explain_hotspot(profile["id"], ranking[0]["id"], "node")
    assert explanation["mapping_proof"][0]["evidence"]["source_onnx_names"] == ["dequant", "quant"]


def test_qnn_viewer_csv_preserves_raw_records_and_units(local):
    core, identifier = local
    filename = Path("tests/fixtures/qnn-viewer-2.50.csv")
    (core.inbox / filename.name).write_bytes(filename.read_bytes())
    result = core.import_profile(identifier, filename.name, "qnn-viewer-csv-v2.50", backend="QNN HTP", fixture=True)
    assert result["raw_format"] == "csv"
    assert result["unit"] == "cycles"
    assert result["latency_us"]["p50"] == 10016
    prof = core.profile(result["id"])
    assert result["profiler_version"] == "v2.50.40.260831140417"
    event = next(row for row in prof["events"] if row["operation"] == "OpId_17")
    assert event["duration"] == 405061
    assert event["start"] is None
    assert event["recorded_timestamp_us"] == 506040810170
    assert core.profile_event(result["id"], event["id"])["raw"][2:4] == ["405061", "CYCLES"]
    assert core.get_hotspots(result["id"], level="node")["hotspots"][0]["total_us"] is None
    assert core.item(result["id"], "trace.csv").read_bytes() == filename.read_bytes()


def test_device_artifact_joins_normalized_htp_operation_id(local):
    core, model_id = local
    trace = Path("tests/fixtures/qnn-optrace-2.50.json")
    (core.inbox / trace.name).write_bytes(trace.read_bytes())
    profile = core.import_profile(model_id, trace.name, "qnn-optrace-chrome-v2.50", fixture=True)
    pid = profile["id"]
    for format in ("qhas-v1.0", "htp-graph-v1.0"):
        filename = Path("tests/fixtures") / (format + ".json")
        (core.inbox / filename.name).write_bytes(filename.read_bytes())
        evidence = core.import_evidence(pid, filename.name, format, "fixture")
        assert core.import_evidence(pid, filename.name, format, "fixture")["id"] == evidence["id"]
        assert (core.evidence_path(pid, evidence["id"]) / "raw.json").read_bytes() == filename.read_bytes()
    event = core.profile(pid)["events"][0]
    related = core.profile_event(pid, event["id"])["related_evidence"]
    assert {item["artifact_type"] for item in related} == {"QHAS", "HTP_GRAPH"}
    assert all(item["operation_records"] for item in related)
    assert core.profile_evidence(pid, "0xFFFF")["artifacts"] == []
    with pytest.raises(ValueError, match="Expected QAIRT"):
        core.import_evidence(pid, "qhas-v1.0.json", "htp-graph-v1.0")


def test_comparison_explains_mismatched_run_conditions(local):
    core, model_id = local
    baseline = core.run_ort_profile(model_id, "test.npz", warmup=1, repeats=2, trace_runs=1)
    candidate = core.run_ort_profile(model_id, "test.npz", warmup=1, repeats=3, trace_runs=1)
    compared = core.compare_experiments(baseline["id"], candidate["id"])
    assert compared["latency"]["comparison_issues"] == [{"field": "repeats", "problem": "different"}]
    assert compared["latency"]["p50"]["delta_pct"] is None
    assert compared["numeric"]["passed"]
    assert "repeats · different" in core.report(compared["id"])
