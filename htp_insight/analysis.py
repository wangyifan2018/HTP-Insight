from collections import defaultdict

from .schema import Hotspot, OptimizationHypothesis

SCOPE = "Sum of complete operation-event durations in this trace (includes Unknown; may overlap)"
CYCLE_SCOPE = "Sum of foreground operation cycles in the QAIRT linting view (includes Unknown; excludes waits and overlap tracks)"
OPTRACE_SCOPE = "Sum of unique measured HTP operation cycles (includes Unknown and overlapping work)"


def timing_scope(session):
    if session.unit == "cycles":
        return OPTRACE_SCOPE if session.source == "Optrace" else CYCLE_SCOPE
    return SCOPE


def rank(graph, session, level):
    if level not in {"node", "module"}:
        raise ValueError("Rank level must be node or module")
    nodes = {node.id: node for node in graph.nodes}
    mappings = defaultdict(set)
    for mapping in session.mappings:
        for operation in mapping.operation_ids:
            mappings[operation].update(mapping.node_ids)
    buckets = defaultdict(list)
    denominator = 0
    for event in session.events:
        if event.kind != "node" or event.duration is None:
            continue
        denominator += event.duration
        ids = tuple(sorted(mappings[event.operation]))
        modules = {nodes[node_id].module for node_id in ids}
        module = next(iter(modules)) if len(modules) == 1 else "Shared" if modules else "Unknown"
        native_operation = event.operation if session.unit == "cycles" and not ids else None
        key = (module, (), None) if level == "module" else (module, ids, native_operation)
        buckets[key].append((event, ids))
    result = []
    for (module, ids, native_operation), pairs in buckets.items():
        total = sum(event.duration for event, _ in pairs)
        all_ids = sorted({node_id for _, mapped in pairs for node_id in mapped})
        key = module if level == "module" else native_operation or "+".join(ids) or "unknown"
        if native_operation:
            label = pairs[0][0].name.removesuffix(" (cycles)")
        else:
            label = nodes[ids[0]].op if len(ids) == 1 else "Mapped operation group" if ids else module
        result.append(Hotspot(
            id=key, label=label, module=module, node_ids=all_ids, unit=session.unit,
            total_us=total if session.unit == "us" else None,
            total_cycles=total if session.unit == "cycles" else None,
            share=total / denominator if denominator else None,
            scope=timing_scope(session), calls=len(pairs),
            evidence_ids=[event.id for event, _ in pairs],
        ))
    return sorted(result, key=lambda item: (-(item.total_us or item.total_cycles or 0), item.id))


def hypothesis(module, ops):
    metrics = ["Uninstrumented p50 and p95 on identical inputs", "Per-module trace duration and operation count",
               "Output allclose and maximum absolute error"]
    if module == "attention":
        return OptimizationHypothesis(
            mechanism="Separate Q, K and V projections may increase dispatch work and reread the same input.",
            adaptation="Concatenate Q, K and V weights and biases, execute one projection, and split its output.",
            metrics=metrics, risk="Changed matrix dimensions can change kernel choice and floating-point rounding.",
        )
    if ops & {"QuantizeLinear", "DequantizeLinear"}:
        return OptimizationHypothesis(
            mechanism="Quantization boundaries may add format conversion and intermediate tensor traffic.",
            adaptation="Test a graph rewrite that removes redundant Q/DQ boundaries with identical encodings.",
            metrics=metrics, risk="Mismatched scales, axes or zero points can change values and calibration.",
        )
    return OptimizationHypothesis(
        mechanism="Operator dispatch, computation, and tensor traffic all contribute to this measured duration.",
        adaptation="Vary one operator or layout within the affected module and compare matched CPU runs.",
        metrics=metrics, risk="Kernel choice varies with shape and backend.",
    )
