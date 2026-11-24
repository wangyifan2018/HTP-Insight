"""Build a Notebook handoff from the selected source graph and capture."""


HTP_BACKEND = "QNN HTP"


def adaptation(graph, hotspot, session):
    htp = session.backend == HTP_BACKEND
    if not hotspot["node_ids"]:
        return {"kind": "attribution_required", "mechanism": "The event has no reliable source node mapping.",
                "change": "Recover compiler mapping for this event before proposing a model edit.",
                "risk": "Attributing this work by operation name alone can target the wrong module."}

    by_id = {node.id: node for node in graph.nodes}
    # Identify QK^T by its dataflow into Softmax, optionally through score scaling.
    if htp and hotspot["module"] == "attention":
        for softmax in graph.nodes:
            if softmax.op != "Softmax" or softmax.module != "attention":
                continue
            for parent in softmax.predecessors:
                scale = by_id[parent]
                scores = scale.predecessors if scale.op in {"Div", "Mul"} else [parent]
                for identifier in scores:
                    node = by_id[identifier]
                    if node.op != "MatMul" or node.id not in hotspot["node_ids"] or len(node.inputs) != 2:
                        continue
                    shapes = [graph.tensors[name].shape for name in node.inputs]
                    if all(shape is not None and len(shape) == 4 for shape in shapes):
                        return {
                            "kind": "hypothesis", "target_node": node.id,
                            "mechanism": "The rank-4 score MatMul may lower to a different layout from a rank-3 batched MatMul.",
                            "change": "In the Notebook model, flatten batch and head on both score MatMul inputs, perform the same QKᵀ product, then restore the axes before score scaling and Softmax. Keep Q/K/V projections, weights and the remaining graph unchanged.",
                            "risk": "The compiler may choose the same layout or insert extra conversions. The changed graph requires independent calibration and device accuracy verification.",
                        }
    if htp:
        return {"kind": "hypothesis", "mechanism": "Compiler lowering may introduce work within the mapped operation group.",
                "change": "Use the matched HTP operations and tensor edges to identify one redundant layout or quantization boundary. Change only that boundary after confirming equivalent tensor semantics in the source Notebook.",
                "risk": "Backend layout, kernel choice and quantization may change; test the compiled artifact."}
    return {"kind": "hypothesis", "mechanism": hotspot["hypothesis"]["mechanism"],
            "change": hotspot["hypothesis"]["adaptation"], "risk": hotspot["hypothesis"]["risk"]}


def validation(session):
    htp = session.backend == HTP_BACKEND
    local = session.source == "ORT" and session.backend == "CPUExecutionProvider"
    fp32 = {"atol": 1e-5, "rtol": 1e-4,
            "checks": "Use identical held-out inputs. Verify shapes, dtypes, finite values, elementwise allclose, and maximum/mean absolute error for PyTorch and exported ONNX outputs."}
    quantization = (
        "Regenerate encodings for changed quantized tensors using identical calibration inputs, bitwidths and recipe. Build both variants with matched tools and check compiled I/O encodings. Use the model's documented device tolerances before measuring performance."
        if htp else "Keep the original precision and encodings for an FP32 layout experiment. Revalidate or regenerate affected encodings if the target graph is quantized."
    )
    if htp:
        capture = "Run matched QAIRT Basic captures for graph execution p50 and p95. Keep Optrace cycles, resource events and QHAS metrics as separate observations."
        reimport = "Register the candidate ONNX and encodings with import_model. Use the Android runner, or import the official Basic CSV and matched Optrace with framework CSV via import_profile. Attach QHAS and HTP Graph through import_evidence."
    elif local:
        capture = "Run uninstrumented ORT CPU samples for p50 and p95 and a separate Chrome Trace for operation attribution."
        reimport = "Register the candidate with import_model, then call run_ort_profile with the original NPZ and matched settings."
    else:
        capture = "Acquire matched runs on the original backend and declare the latency metric and profiling overhead before comparing."
        reimport = "Register the candidate with import_model and import the matching profiler export with import_profile."
    return {
        "numeric": {"fp32": fp32, "device": "Compare each compiled variant against its FP32 reference and check device A/B on held-out inputs." if htp else None},
        "quantization": quantization,
        "acceptance": {
            "capture": capture,
            "matched_conditions": ["backend and device", "SDK or runtime version", "input digest and shapes",
                                   "precision and I/O", "warmup and retained samples", "profiling level and performance settings"],
            "paired_blocks": 6, "minimum_p50_wins": 5, "minimum_p50_improvement_pct": 5,
            "maximum_p95_increase_pct": 2,
            "decision": "Require numerical agreement, p50 improvement above the measured A/A variation and at least 5% in aggregate, p50 wins in at least 5 of 6 paired blocks, and at most 2% increase in p95. Record inconclusive results if variability or missing matched evidence prevents a decision.",
        },
        "reimport": reimport + " Use compare_experiments on the matched Profile IDs and report graph changes and output verification.",
    }


def markdown(plan):
    model = plan["model"]
    profile = plan["profile"]
    hot = plan["hotspot"]
    latency = profile["latency_us"] or {}
    change = plan["adaptation"]
    validation = plan["validation"]
    reading = "Unavailable" if not latency else f"{latency.get('p50')} / {latency.get('p95')} µs · {latency.get('label') or latency.get('scope')}"
    cost = hot["total_cycles"] if hot["unit"] == "cycles" else hot["total_us"]
    share = f"{hot['share']:.2%}" if hot["share"] is not None else "Unavailable"
    lines = [
        "# Claude Code Notebook Adaptation", "",
        f"Model {model['name']} (`{model['id']}`), architecture {model['architecture']}",
        f"Profile `{profile['id']}` · {profile['backend'] or 'Backend unavailable'} · {profile['source']} · {profile['provenance']}",
        f"Device {profile['device'] or 'Unavailable'} · Profiler {profile['profiler_version'] or 'Unavailable'}",
        f"Graph execution p50 / p95: {reading}", "",
        "## Observed evidence", "",
        f"{hot['module']} · {hot['label']} (`{hot['id']}`) · {cost} {hot['unit']} · {share}",
        hot["scope"], "",
    ]
    if profile["provenance"] != "measured":
        lines.append("The recorded timings were imported. Verify the capture origin and settings before making a performance claim.")
    for evidence in plan["evidence"]:
        event = evidence["event"]
        lines.append(f"- [{event['id']}]({evidence['deep_link']}) · {event['name']} · {event['duration']} {event['unit']} · {event['resource'] or 'Resource unavailable'} · [Original record]({evidence['raw_url']})")
        if evidence["artifacts"]:
            lines.extend(f"  - [{item['artifact_type']}]({item['link']}) (`{item['id']}`)" for item in evidence["artifacts"])
    lines.extend(["", "## Source structure and mapping", "", plan["mapping"], ""])
    lines.append(f"Graph: {model['node_count']} nodes, {model['initializer_elements']} initializer elements, quantization annotations {', '.join(model['quantization_formats']) or 'unavailable'}.")
    for node in plan["nodes"]:
        inputs = ", ".join(f"{t['dtype'] or '?'} {t['shape']}" for t in node["input_tensors"])
        outputs = ", ".join(f"{t['dtype'] or '?'} {t['shape']}" for t in node["output_tensors"])
        encodings = ", ".join(f"{q['format']} {q['bitwidth'] or '?'}-bit" for q in node["quantization_details"])
        lines.append(f"- `{node['id']}` {node['name'] or node['op']} · {inputs or 'Unavailable'} → {outputs or 'Unavailable'} · {encodings or 'Encoding unavailable'}")
    lines.extend([
        "", "## Adaptation hypothesis", "", change["mechanism"], change["change"], change["risk"],
        "Inspect the original Notebook and confirm the operator correspondence before changing the model. Preserve its public I/O, original artifacts and experiment inputs.",
        "", "## Numerical and A/B acceptance", "", validation["numeric"]["fp32"]["checks"],
        "FP32 tolerances are atol=1e-5 and rtol=1e-4.", validation["quantization"],
    ])
    if validation["numeric"]["device"]:
        lines.append(validation["numeric"]["device"])
    lines.extend([
        "Match " + ", ".join(validation["acceptance"]["matched_conditions"]) + ".",
        validation["acceptance"]["capture"], validation["acceptance"]["decision"],
        "", "## Baseline capture settings", "",
    ])
    settings = profile["conditions"]
    for field in ("input_sha256", "input_shape", "precision", "perf_profile", "profiling_level", "warmup", "repeats", "trace_runs"):
        if settings.get(field) is not None:
            lines.append(f"- {field}: `{settings[field]}`")
    lines.extend([
        "", "## Reimport and report", "", validation["reimport"],
        "Record original measurements, numerical errors, mapping coverage and supported conclusions. Leave unavailable observations empty.",
        "", f"[Hotspot and evidence]({plan['deep_link']})", "",
    ])
    return "\n".join(lines)
