import hashlib
import json
import math
import os
import platform
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np

from . import analysis, experiment_plan, graph, profiles, qnn, qnn_evidence
from .qnn_csv import csv_rows
from .schema import ExperimentResult, Graph, ModelArtifact, NodeMapping, ProfileSession

ROOT = Path(__file__).resolve().parents[1]
ID_PATTERN = re.compile(r"(?:model|profile|experiment)-[a-f0-9]{24}")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False).encode()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


class Core:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv("HTP_INSIGHT_DATA", ROOT / "runs")).resolve()
        self.inbox = self.root / "inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.web_url = os.getenv("HTP_INSIGHT_WEB", "http://127.0.0.1:8000").rstrip("/")

    def link(self, page, **query):
        return f"{self.web_url}/?{urlencode({'view': page, **query})}"

    def inbox_path(self, name, extensions):
        path = (self.inbox / name).resolve()
        if not path.is_relative_to(self.inbox) or path.suffix.lower() not in extensions or not path.is_file():
            raise ValueError(f"Expected existing {'/'.join(sorted(extensions))} file under the inbox")
        return path

    def item(self, identifier, filename):
        if not ID_PATTERN.fullmatch(identifier):
            raise ValueError("Invalid evidence identifier")
        return self.root / "store" / identifier / filename

    def read(self, identifier, filename):
        with self.item(identifier, filename).open() as handle:
            return json.load(handle)

    def graph(self, model_id):
        return Graph.model_validate(self.read(model_id, "graph.json"))

    def session(self, profile_id):
        return ProfileSession.model_validate(self.read(profile_id, "profile.json"))

    def import_model(self, filename: str, encodings: str | None = None, name: str | None = None,
                     origin: str | None = None, target_device: str | None = None,
                     compatibility: dict | None = None) -> dict[str, Any]:
        path = self.inbox_path(filename, {".onnx", ".bin"})
        model = graph.read_model(path) if path.suffix.lower() == ".onnx" else None
        payload = model.SerializeToString(deterministic=True) if model is not None else path.read_bytes()
        raw_enc = self.inbox_path(encodings, {".json", ".encodings"}).read_bytes() if encodings else b""
        parsed_enc = graph.parse_encodings(json.loads(raw_enc)) if encodings else None
        if model is None and encodings:
            raise ValueError("Encodings require an ONNX graph")
        model_sha = digest(payload)
        identity = json.dumps([model_sha, digest(raw_enc), path.suffix.lower(), name or path.stem, origin,
                               target_device, compatibility], sort_keys=True)
        model_id = f"model-{digest(identity.encode())[:24]}"
        artifact = ModelArtifact(
            id=model_id, sha256=model_sha, name=name or path.stem, format="ONNX" if model is not None else "HTP_CONTEXT",
            origin=origin, target_device=target_device, compatibility=compatibility or {},
        )
        if model is not None:
            result = graph.inspect(model, artifact, parsed_enc)
            atomic_write(self.item(model_id, "model.onnx"), payload)
            if encodings:
                atomic_write(self.item(model_id, "encodings.json"), raw_enc)
            atomic_write(self.item(model_id, "graph.json"), encode(result.model_dump()))
        else:
            atomic_write(self.item(model_id, "context.bin"), payload)
        atomic_write(self.item(model_id, "artifact.json"), encode(artifact.model_dump()))
        return {"artifact": artifact.model_dump(), "deep_link": self.link("graph", model=model_id)}

    def inspect_graph(self, model_id: str) -> dict[str, Any]:
        return {**self.graph(model_id).model_dump(), "deep_link": self.link("graph", model=model_id)}

    def save_profile(self, model_id, raw, format, provenance, backend=None, profiler_version=None, device=None,
                     conditions=None, latency=None, outputs=None, mappings=None):
        if format not in profiles.ADAPTERS:
            raise ValueError(f"Supported profile formats: {', '.join(profiles.ADAPTERS)}. Other formats are Future Integration.")
        if provenance not in {"measured", "imported", "fixture"}:
            raise ValueError("Invalid profile provenance")
        adapter = profiles.ADAPTERS[format]
        model = self.graph(model_id)
        metadata = [model_id, format, provenance, backend, profiler_version, device, conditions, latency, mappings]
        profile_id = f"profile-{digest(json.dumps(metadata, sort_keys=True).encode() + raw)[:24]}"
        session = ProfileSession(
            id=profile_id, model_id=model_id, source=adapter.source, provenance=provenance, backend=backend,
            profiler_version=profiler_version, device=device or {}, conditions={**(conditions or {}), "adapter": format},
            events=[], mappings=[], latency_us=latency, raw_format=getattr(adapter, "extension", "json"),
        )
        adapter.parse(raw, session, model)
        if mappings is not None:
            supplied = [NodeMapping.model_validate({**entry, "method": "provided"}) for entry in mappings]
            graph_ids = {node.id for node in model.nodes}
            operation_ids = {event.operation for event in session.events if event.operation is not None}
            if any(not item.operation_ids or not set(item.operation_ids) <= operation_ids
                   or not item.node_ids or not set(item.node_ids) <= graph_ids for item in supplied):
                raise ValueError("Mapping references an unknown operation or graph node")
            overridden = {operation for item in supplied for operation in item.operation_ids}
            session.mappings = supplied + [item for item in session.mappings if not overridden.intersection(item.operation_ids)]
        atomic_write(self.item(profile_id, f"trace.{session.raw_format}"), raw)
        if outputs is not None:
            atomic_write(self.item(profile_id, "outputs.npz"), outputs)
        atomic_write(self.item(profile_id, "profile.json"), encode(session.model_dump()))
        return self.profile_summary(session)

    def profile_summary(self, session):
        return {
            **session.model_dump(exclude={"events", "mappings"}), "event_count": len(session.events),
            "operation_event_count": sum(event.kind == "node" and event.duration is not None for event in session.events),
            "deep_link": self.link("timeline", profile=session.id), "raw_trace": f"/api/profiles/{session.id}/raw",
        }

    def import_profile(self, model_id: str, filename: str, format: str = "ort-chrome-v1", fixture: bool = False,
                       backend: str | None = None, profiler_version: str | None = None,
                       device: dict | None = None, conditions: dict | None = None, mapping_file: str | None = None,
                       framework_csv: str | None = None) -> dict[str, Any]:
        adapter = profiles.ADAPTERS.get(format)
        if adapter is None:
            raise ValueError(f"Supported profile formats: {', '.join(profiles.ADAPTERS)}. Other formats are Future Integration.")
        raw = self.inbox_path(filename, {"." + getattr(adapter, "extension", "json")}).read_bytes()
        mapping = json.loads(self.inbox_path(mapping_file, {".json"}).read_bytes()) if mapping_file else None
        if framework_csv:
            if format != "qnn-optrace-chrome-v2.50" or mapping is not None:
                raise ValueError("Framework CSV requires the QAIRT 2.50 Optrace format and a single mapping source")
            framework = self.inbox_path(framework_csv, {".csv"}).read_bytes()
            mapping = qnn.optrace_onnx_mappings(raw, framework, self.graph(model_id))
        if mapping is not None and (not isinstance(mapping, list) or any(not isinstance(x, dict) for x in mapping)):
            raise ValueError("Expected a list of operation-to-node mappings")
        return self.save_profile(model_id, raw, format, "fixture" if fixture else "imported",
                                 backend, profiler_version, device, conditions, mappings=mapping)

    def run_ort_profile(self, model_id: str, inputs: str, warmup: int = 30, repeats: int = 200, trace_runs: int = 5) -> dict[str, Any]:
        model = self.item(model_id, "model.onnx")
        sample = self.inbox_path(inputs, {".npz"})
        if not model.is_file():
            raise ValueError("ORT profiling requires an imported ONNX model")
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            work = Path(folder)
            raw, latency, conditions, version = profiles.benchmark(model, sample, work, warmup, repeats, trace_runs)
            device = {"os": platform.system(), "os_version": platform.mac_ver()[0] or platform.release(),
                      "arch": platform.machine(), "cpu": platform.processor() or None}
            return self.save_profile(model_id, raw, "ort-chrome-v1", "measured", "CPUExecutionProvider", version,
                                     device, conditions, latency, (work / "outputs.npz").read_bytes())

    def profile(self, profile_id):
        session = self.session(profile_id)
        return {**self.profile_summary(session), "events": [event.model_dump() for event in session.events],
                "mappings": [item.model_dump() for item in session.mappings],
                "evidence": self.profile_evidence(profile_id)["artifacts"]}

    def import_evidence(self, profile_id: str, filename: str, format: str,
                        provenance: str = "imported") -> dict[str, Any]:
        self.session(profile_id)
        if provenance not in {"imported", "measured", "estimated", "fixture"}:
            raise ValueError("Evidence provenance must be imported, measured, estimated or fixture")
        raw = self.inbox_path(filename, {".json"}).read_bytes()
        specification, operations = qnn_evidence.parse_evidence(json.loads(raw), format)
        sha = digest(raw)
        identifier = "evidence-" + digest(encode([profile_id, format, provenance, sha]))[:24]
        directory = self.evidence_path(profile_id, identifier)
        metadata = {
            "id": identifier, "profile_id": profile_id, "format": format, "provenance": provenance,
            "sha256": sha, "filename": Path(filename).name, **specification,
            "raw": f"/api/profiles/{profile_id}/evidence/{identifier}/raw",
            "deep_link": self.link("timeline", profile=profile_id),
        }
        atomic_write(directory / "raw.json", raw)
        atomic_write(directory / "operations.json", encode(operations))
        atomic_write(directory / "index.json", encode(metadata))
        return metadata

    def evidence_path(self, profile_id, evidence_id):
        if not re.fullmatch(r"evidence-[a-f0-9]{24}", evidence_id):
            raise ValueError("Invalid attachment evidence ID")
        return self.item(profile_id, "evidence") / evidence_id

    def profile_evidence(self, profile_id: str, operation_id: str | None = None) -> dict[str, Any]:
        self.session(profile_id)
        identifier = qnn_evidence.native_id(operation_id)
        artifacts = []
        for index in sorted(self.item(profile_id, "evidence").glob("evidence-*/index.json")):
            record = json.loads(index.read_bytes())
            if identifier is not None:
                rows = json.loads((index.parent / "operations.json").read_bytes()).get(identifier)
                if rows:
                    artifacts.append({**record, "operation_records": rows})
            elif operation_id is None:
                artifacts.append(record)
        return {"profile_id": profile_id, "operation_id": operation_id, "artifacts": artifacts}

    def profile_event(self, profile_id: str, event_id: str) -> dict[str, Any]:
        session = self.session(profile_id)
        event = next((item for item in session.events if item.id == event_id), None)
        if event is None:
            raise FileNotFoundError("Event unavailable")
        if session.raw_format == "csv":
            rows = csv_rows(self.item(profile_id, "trace.csv").read_bytes())
        else:
            document = self.read(profile_id, "trace.json")
            rows = document["traceEvents"] if isinstance(document, dict) else document
        return {"event": event.model_dump(), "raw": rows[event.raw_index],
                "related_evidence": self.profile_evidence(profile_id, event.operation)["artifacts"] if event.operation else []}

    def get_hotspots(self, profile_id: str, level: str = "module", limit: int = 10) -> dict[str, Any]:
        if not 1 <= limit <= 10000:
            raise ValueError("Limit must be 1–10000")
        session = self.session(profile_id)
        model = self.graph(session.model_id)
        return {
            "profile_id": profile_id, "backend": session.backend, "source": session.source,
            "provenance": session.provenance, "unit": session.unit,
            "hotspots": [{**item.model_dump(), "deep_link": self.link("diagnosis", profile=profile_id, hotspot=item.id,
                                                                      level=level)}
                         for item in analysis.rank(model, session, level)[:limit]],
        }

    def explain_hotspot(self, profile_id: str, hotspot_id: str, level: str = "module") -> dict[str, Any]:
        session = self.session(profile_id)
        model = self.graph(session.model_id)
        hotspot = next((item for item in analysis.rank(model, session, level) if item.id == hotspot_id), None)
        if hotspot is None:
            raise ValueError("Unknown hotspot")
        nodes = [node for node in model.nodes if node.id in hotspot.node_ids]
        first_event = next(event for event in session.events if event.id == hotspot.evidence_ids[0])
        suggestion = analysis.hypothesis(hotspot.module, {node.op for node in nodes})
        if hotspot.module in {"Unknown", "Shared"}:
            suggestion.mechanism = "The operation duration is available, but its module attribution is incomplete."
            suggestion.adaptation = "Import compiler mappings and check operation boundaries before editing the graph."
        if session.unit == "cycles":
            suggestion.metrics = ["Operation cycles from equivalent device captures",
                                  "QNN basic-profile execution p50 and p95 on matched inputs", "Output agreement"]
            if hotspot.module not in {"Unknown", "Shared"}:
                suggestion.mechanism = "The device trace exposes operation cycles and hardware resources for the mapped operation."
                suggestion.adaptation = "Run a matched HTP experiment and inspect the affected operation and graph execution."
        evidence_ids = set(hotspot.evidence_ids)
        operation_ids = {event.operation for event in session.events if event.id in evidence_ids}
        mappings = [mapping for mapping in session.mappings if operation_ids.intersection(mapping.operation_ids)]
        mapping_proof = [mapping.model_dump() for mapping in mappings if mapping.evidence]
        result = {
            **hotspot.model_dump(), "mapping_proof": mapping_proof, "source": session.source, "backend": session.backend, "provenance": session.provenance,
            "mapping_methods": sorted({mapping.method for mapping in mappings}),
            "nodes": [{**node.model_dump(), "input_tensors": [model.tensors[t].model_dump() for t in node.inputs if t],
                       "output_tensors": [model.tensors[t].model_dump() for t in node.outputs if t],
                       "quantization_details": [model.quantization[i].model_dump() for i in node.quantization]} for node in nodes],
            "example_evidence": first_event.model_dump(),
            "related_evidence": self.profile_evidence(profile_id, first_event.operation)["artifacts"] if first_event.operation else [],
            "raw_trace": f"/api/profiles/{profile_id}/raw",
            "hypothesis": suggestion.model_dump(),
            "deep_link": self.link("timeline", profile=profile_id, event=first_event.id),
        }
        if session.backend == experiment_plan.HTP_BACKEND:
            result["experiment_hint"] = experiment_plan.adaptation(model, result, session)
        return result

    def generate_experiment_plan(self, profile_id: str, hotspot_id: str, level: str = "module") -> dict[str, Any]:
        session = self.session(profile_id)
        if session.provenance == "fixture":
            raise ValueError("An experiment plan requires a real capture. Fixture timings are excluded.")
        model = self.graph(session.model_id)
        hotspot = self.explain_hotspot(profile_id, hotspot_id, level)
        adaptation = hotspot.get("experiment_hint") or experiment_plan.adaptation(model, hotspot, session)
        target = adaptation.get("target_node")
        target_operations = {operation for mapping in session.mappings if target in mapping.node_ids for operation in mapping.operation_ids}
        evidence_ids = set(hotspot["evidence_ids"])
        events = sorted((event for event in session.events if event.id in evidence_ids),
                        key=lambda event: (event.operation not in target_operations, -(event.duration or 0)))
        evidence = []
        for event in events[:3]:
            artifacts = self.profile_evidence(profile_id, event.operation)["artifacts"] if event.operation else []
            evidence.append({
                "event": event.model_dump(),
                "deep_link": self.link("timeline", profile=profile_id, event=event.id),
                "raw_url": f"{self.web_url}/api/profiles/{profile_id}/events/{event.id}",
                "artifacts": [{**item, "link": self.web_url + item["raw"]} for item in artifacts if item["provenance"] != "fixture"],
            })
        if hotspot["mapping_proof"]:
            mapping = "Source mapping is supported by the provided compiler records. Inspect the operation-to-node links and keep unmatched work Unknown."
        elif hotspot["node_ids"]:
            mapping = "The operation group has source-node links. Review their matching method before attributing individual event duration."
        else:
            mapping = "Source attribution is Unknown. Collect source mapping before editing the model."
        response = {
            "schema_version": 1, "id": "plan-" + digest(encode([1, profile_id, level, hotspot_id]))[:24],
            "model": {**model.artifact.model_dump(), "architecture": model.architecture, "node_count": len(model.nodes),
                      "initializer_elements": model.initializer_elements,
                      "inputs": [model.tensors[name].model_dump() for name in model.inputs],
                      "outputs": [model.tensors[name].model_dump() for name in model.outputs],
                      "quantization_formats": sorted({item.format for item in model.quantization})},
            "profile": {**self.profile_summary(session),
                        "latency_us": {key: value for key, value in session.latency_us.items() if key != "samples"} if session.latency_us else None},
            "hotspot": {key: value for key, value in hotspot.items()
                        if key in {"id", "label", "module", "node_ids", "unit", "share", "scope", "calls", "total_us", "total_cycles", "evidence_ids"}},
            "nodes": hotspot["nodes"], "evidence": evidence, "mapping": mapping,
            "mapping_methods": hotspot["mapping_methods"], "mapping_proof": hotspot["mapping_proof"],
            "adaptation": adaptation, "validation": experiment_plan.validation(session),
            "deep_link": self.link("diagnosis", profile=profile_id, hotspot=hotspot_id, level=level),
        }
        return {**response, "markdown": experiment_plan.markdown(response)}

    def analyze_model_performance(self, profile_id: str, limit: int = 5) -> dict[str, Any]:
        if not 1 <= limit <= 20:
            raise ValueError("Limit must be 1–20")
        ranking = self.get_hotspots(profile_id, limit=limit)
        session = self.session(profile_id)
        model = self.graph(session.model_id)
        top = next((row for row in ranking["hotspots"] if row["node_ids"] and row["module"] != "Shared"), None)
        priority = top or (ranking["hotspots"][0] if ranking["hotspots"] else None)
        pending = []
        plan = None
        if session.provenance == "fixture":
            pending.append("Replace fixture data with a real capture before generating a Notebook task.")
        elif priority:
            plan = self.generate_experiment_plan(profile_id, priority["id"])
        if not top:
            pending.append("Collect mapped operation events before attributing costs to the source graph.")
        if not session.latency_us:
            pending.append("Collect matched graph execution samples to obtain p50 and p95.")
        if any(row["module"] in {"Shared", "Unknown"} for row in ranking["hotspots"]):
            pending.append("Inspect shared or Unknown work using source mapping evidence.")
        latency = {key: value for key, value in session.latency_us.items() if key != "samples"} if session.latency_us else None
        return {**ranking, "model": model.artifact.model_dump(), "profile": {
            "id": profile_id, "device": session.device, "profiler_version": session.profiler_version,
            "conditions": session.conditions, "latency_us": latency, "deep_link": self.link("timeline", profile=profile_id),
        }, "investigate": pending, "next_experiment": plan}

    def suggest_experiments(self, profile_id: str, limit: int = 3) -> dict[str, Any]:
        summary = self.get_hotspots(profile_id, "module", limit)
        summary["suggestions"] = [
            {key: value for key, value in self.explain_hotspot(profile_id, item["id"]).items()
             if key in {"id", "module", "hypothesis", "evidence_ids", "deep_link"}}
            for item in summary.pop("hotspots")
        ]
        return summary

    def compare_experiments(self, baseline: str, candidate: str, hypothesis: str | None = None,
                            atol: float = 1e-5, rtol: float = 1e-4) -> dict[str, Any]:
        if any(not math.isfinite(value) or value < 0 for value in (atol, rtol)):
            raise ValueError("Comparison tolerances must be finite and nonnegative")
        left, right = self.session(baseline), self.session(candidate)
        left_graph, right_graph = self.graph(left.model_id), self.graph(right.model_id)
        reasons = []
        def check(field, before, after, required=False):
            if required and (before is None or after is None or before == {} or after == {}):
                reasons.append({"field": field, "problem": "unavailable"})
            elif before != after:
                reasons.append({"field": field, "problem": "different"})

        check("latency_scope", (left.latency_us or {}).get("scope"), (right.latency_us or {}).get("scope"), required=True)
        check("source", left.source, right.source)
        check("backend", left.backend, right.backend, required=True)
        check("device", left.device, right.device, required=True)
        check("profiler_version", left.profiler_version, right.profiler_version, required=True)
        check("fixture_provenance", left.provenance == "fixture", right.provenance == "fixture")
        keys = ("input_sha256", "warmup", "repeats", "trace_runs", "intra_op_threads", "inter_op_threads",
                "execution_mode", "graph_optimization", "profiling_level", "perf_profile", "precision",
                "capture_protocol", "native_io", "model_format", "runs")
        for key in keys:
            check(key, left.conditions.get(key), right.conditions.get(key), required=key == "input_sha256")

        matched = not reasons
        latency = {"comparable": matched, "unit": "us"}
        if reasons:
            latency["comparison_issues"] = reasons
        if matched and left.latency_us.get("label"):
            latency["label"] = left.latency_us["label"]
        for key in ("p50", "p95"):
            before = left.latency_us.get(key) if left.latency_us else None
            after = right.latency_us.get(key) if right.latency_us else None
            latency[key] = {"baseline": before, "candidate": after,
                            "delta_pct": (after / before - 1) * 100 if matched and before and after is not None else None}
        numeric = None
        a_path, b_path = (self.item(identifier, "outputs.npz") for identifier in (baseline, candidate))
        if (left.conditions.get("input_sha256") and left.conditions["input_sha256"] == right.conditions.get("input_sha256")
                and left.conditions.get("verification_input_sha256") == right.conditions.get("verification_input_sha256")):
            if a_path.is_file() and b_path.is_file():
                with np.load(a_path, allow_pickle=False) as a, np.load(b_path, allow_pickle=False) as b:
                    try:
                        numeric = profiles.output_error(dict(a.items()), dict(b.items()), atol=atol, rtol=rtol)
                    except ValueError as exc:
                        numeric = {"passed": False, "error": str(exc)}
        a_costs = {item.module: item for item in analysis.rank(left_graph, left, "module")}
        b_costs = {item.module: item for item in analysis.rank(right_graph, right, "module")}
        module_costs = []
        for module in sorted(a_costs.keys() | b_costs.keys()):
            row = {"module": module}
            for side, bucket, session in (("baseline", a_costs, left), ("candidate", b_costs, right)):
                cost = bucket.get(module)
                row[f"{side}_us"] = cost.total_us if cost else None
                if session.unit == "cycles":
                    row[f"{side}_cycles"] = cost.total_cycles if cost else None
            module_costs.append(row)
        identity = [baseline, candidate, hypothesis]
        if (atol, rtol) != (1e-5, 1e-4):
            identity += [atol, rtol]
        identifier = f"experiment-{digest(encode(identity))[:24]}"
        result = ExperimentResult(
            id=identifier, baseline=baseline, candidate=candidate, hypothesis=hypothesis, numeric=numeric,
            latency=latency, graph_diff=graph.diff(left_graph, right_graph),
            module_costs=module_costs,
        )
        response = {**result.model_dump(), "deep_link": self.link("diagnosis", experiment=identifier, profile=baseline),
                    "trace_runs": {"baseline": left.conditions.get("trace_runs"), "candidate": right.conditions.get("trace_runs")},
                    "sources": {"baseline": [left.source, left.backend, left.provenance],
                                "candidate": [right.source, right.backend, right.provenance]}}
        atomic_write(self.item(identifier, "experiment.json"), encode(response))
        return response

    def catalog(self):
        return {
            key: [json.loads(path.read_bytes()) for path in sorted((self.root / "store").glob(pattern),
                    key=lambda entry: entry.stat().st_mtime, reverse=True)]
            for key, pattern in (("models", "model-*/artifact.json"), ("experiments", "experiment-*/experiment.json"))
        } | {"profiles": [self.profile_summary(ProfileSession.model_validate_json(path.read_bytes()))
                         for path in sorted((self.root / "store").glob("profile-*/profile.json"),
                                            key=lambda entry: entry.stat().st_mtime, reverse=True)]}

    def workspace_status(self):
        catalog = self.catalog()
        models = {model["id"]: model for model in catalog["models"]}
        measured = {profile["id"]: profile for profile in catalog["profiles"] if profile["provenance"] == "measured"}
        ort_available = "CPUExecutionProvider" in profiles.ort.get_available_providers()
        examples = []
        for backend in ("CPUExecutionProvider", "QNN HTP"):
            eligible = [experiment for experiment in catalog["experiments"]
                        if experiment["baseline"] in measured and experiment["candidate"] in measured
                        and measured[experiment["baseline"]]["backend"] == backend
                        and measured[experiment["baseline"]]["model_id"] in models
                        and experiment["latency"]["comparable"] and (experiment["numeric"] or {}).get("passed")]
            if not eligible:
                continue
            experiment = max(eligible, key=lambda row: (
                models[measured[row["baseline"]]["model_id"]]["name"].startswith("Tiny Transformer"),
                measured[row["baseline"]]["conditions"].get("repeats") or 0,
            ))
            profile = measured[experiment["baseline"]]
            model = models[profile["model_id"]]
            examples.append({
                "model": model["name"], "model_id": model["id"], "profile_id": profile["id"],
                "experiment_id": experiment["id"], "backend": backend, "device": profile["device"], "latency": experiment["latency"],
            })
        captures = [{"id": profile["id"], "adapter": profile["conditions"].get("adapter"),
                     "backend": profile["backend"], "source": profile["source"]} for profile in measured.values()]
        return {"ort_cpu_available": ort_available, "measured_captures": captures, "examples": examples}

    def report(self, experiment_id):
        exp = self.read(experiment_id, "experiment.json")
        profiles = [self.session(exp[key]) for key in ("baseline", "candidate")]
        lines = ["# HTP Insight experiment", "", f"Experiment `{exp['id']}`", "",
                 exp["hypothesis"] or "Hypothesis unavailable", "",
                 f"| {exp['latency'].get('label', 'Uninstrumented latency')} | Baseline (µs) | Candidate (µs) | Change |",
                 "| --- | ---: | ---: | ---: |"]
        def display(value):
            return "Unavailable" if value is None else f"{value:.3f}"

        for metric in ("p50", "p95"):
            row = exp["latency"][metric]
            change = f"{row['delta_pct']:+.2f}%" if row["delta_pct"] is not None else "Unavailable"
            lines.append(f"| {metric} | {display(row['baseline'])} | {display(row['candidate'])} | {change} |")
        if exp["latency"].get("comparison_issues"):
            issues = exp["latency"]["comparison_issues"]
            lines.extend(["", "Latency comparison unavailable."] + [
                f"- {issue['field']} · {issue['problem']}" for issue in issues
            ])
        lines.extend(["", "## Numerical validation", "", "```json", json.dumps(exp["numeric"], indent=2), "```",
                      "", "## Trace evidence", "",
                      "| Semantic module | Baseline operation sum | Candidate operation sum |",
                      "| --- | ---: | ---: |"])
        for row in exp["module_costs"]:
            measures = []
            for side, session in zip(("baseline", "candidate"), profiles):
                metric = row.get(f"{side}_{session.unit}")
                suffix = "µs" if session.unit == "us" else "cycles"
                measures.append(f"{display(metric)} {suffix}" if metric is not None else "Unavailable")
            lines.append(f"| {row['module']} | {measures[0]} | {measures[1]} |")
        lines.append("")
        for session in profiles:
            top = self.get_hotspots(session.id, limit=1)["hotspots"]
            lines.append(f"- {session.source} / {session.backend} / {session.provenance}, device {session.device}. "
                         f"[Timeline]({self.link('timeline', profile=session.id)})"
                         + (f", strongest bucket {top[0]['module']}, evidence `{top[0]['evidence_ids'][0]}`." if top else "."))
        scopes = sorted({analysis.timing_scope(session) for session in profiles})
        lines.extend(["", *scopes, "",
                      f"Operation-duration sums cover {exp['trace_runs']} sampled runs.", "",
                      "## Experiment conditions", "", "```json",
                      json.dumps({name: {"profiler_version": session.profiler_version, "conditions": session.conditions}
                                  for name, session in zip(("baseline", "candidate"), profiles)}, indent=2), "```", "",
                      "## Graph changes", "", "```json", json.dumps(exp["graph_diff"], indent=2), "```", ""])
        return "\n".join(lines)
