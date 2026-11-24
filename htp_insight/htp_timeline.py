"""Evidence-based resource, dependency, and wait analysis for QAIRT Optrace."""

from collections import defaultdict
import re

from .profiles import finite_number
from .qnn_evidence import native_id

OVERVIEW = re.compile(r"Core (\d+) Overview")
CORE_THREAD = re.compile(r"Core:\s*(\d+)\s+Type:\s*([A-Za-z0-9_]+)\s+Tid:\s*(\d+)")
THREAD = re.compile(r"Type:\s*([A-Za-z0-9_]+)")
FLOWS = {"input_output": "trace_data", "sequencer": "trace_sequencer"}
FLOW_KINDS = frozenset(FLOWS.values())


def operation_key(row):
    args = row.get("args", {})
    if row.get("ph") == "X" and isinstance(args, dict) and "Start Cycle" in args and "Duration (cycles)" in args:
        identifier = native_id(args.get("ID"))
        if identifier and isinstance(args["Start Cycle"], (int, float)) and isinstance(args["Duration (cycles)"], (int, float)):
            return identifier, args["Start Cycle"], args["Duration (cycles)"]
    return None


def physical_tracks(rows):
    cores, labels = {}, {}
    for row in rows:
        args = row.get("args")
        if row.get("ph") != "M" or not isinstance(args, dict) or not isinstance(args.get("name"), str):
            continue
        pid, tid, name = row.get("pid"), row.get("tid"), args["name"]
        if row.get("name") == "process_name" and (match := OVERVIEW.fullmatch(name)):
            cores[pid] = int(match[1])
        if row.get("name") == "thread_name" and isinstance(tid, int):
            labels[pid, tid] = name
    tracks = {}
    for (pid, tid), name in labels.items():
        explicit = CORE_THREAD.fullmatch(name)
        overview = THREAD.fullmatch(name)
        if explicit and tid == int(explicit[3]):
            tracks[pid, tid] = (int(explicit[1]), explicit[2].upper(), tid)
        elif overview and pid in cores:
            tracks[pid, tid] = (cores[pid], overview[1].upper(), tid)
    return tracks, cores


def qhas_tracks(attachments):
    assignments = defaultdict(set)
    for evidence_id, tables in attachments:
        types = {}
        for core in tables.get("htp_overall_summary", {}).get("data", []):
            core_id = core.get("htp")
            if not isinstance(core_id, int):
                continue
            for row in (core.get("htp_resources") or {}).get("data", []):
                tid = row.get("tid")
                if isinstance(tid, int):
                    types[core_id, tid] = row.get("type")
        for row in tables.get("htp_op_instances", {}).get("data", []):
            core, tid = row.get("htp"), row.get("tid")
            start, cycles = row.get("start_cycle"), row.get("cycles")
            if not isinstance(core, int) or not isinstance(tid, int) or not finite_number(start) or not finite_number(cycles):
                continue
            kind = types.get((core, tid))
            identifier = native_id(row.get("op_id"))
            if identifier and isinstance(kind, str):
                assignments[identifier, start, cycles].add(((core, kind.upper(), tid), evidence_id))
    return assignments


def compiled_edges(graphs, operation_events, add):
    for evidence_id, rows in graphs:
        producers = defaultdict(set)
        for identifier, records in rows.items():
            for record in records:
                for tensor in record.get("output_tensors") or []:
                    if key := native_id(tensor):
                        producers[key].add(identifier)
        for identifier, records in rows.items():
            if len(operation_events[identifier]) != 1:
                continue
            target, = operation_events[identifier]
            for record in records:
                for tensor in record.get("input_tensors") or []:
                    key = native_id(tensor)
                    if len(producers.get(key, ())) != 1:
                        continue
                    producer, = producers[key]
                    if len(operation_events[producer]) == 1:
                        add(operation_events[producer][0], target, {"kind": "compiled_tensor", "tensor": tensor, "artifact_id": evidence_id})


def trace_edges(rows, cores, starts, ends, add):
    flows = defaultdict(lambda: defaultdict(list))
    for index, row in enumerate(rows):
        phase, category, flow_id = row.get("ph"), row.get("cat"), row.get("id")
        if (phase in ("s", "f") and isinstance(category, str) and category in FLOWS
                and isinstance(flow_id, (int, str)) and isinstance(row.get("pid"), int) and row["pid"] in cores
                and isinstance(row.get("tid"), int) and finite_number(row.get("ts"))):
            flows[row["pid"], category, flow_id][phase].append((index, row))
    unresolved = 0
    for (_, category, flow_id), pair in flows.items():
        if len(pair["s"]) != 1 or len(pair["f"]) != 1:
            unresolved += 1
            continue
        (left, start), = pair["s"]
        (right, end), = pair["f"]
        source = ends.get((start["pid"], start.get("tid"), start.get("ts")), ())
        target = starts.get((end["pid"], end.get("tid"), end.get("ts")), ())
        if len(source) == len(target) == 1 and source != target:
            add(next(iter(source)), next(iter(target)), {"kind": FLOWS[category], "flow_id": flow_id, "raw_indices": [left, right]})
        else:
            unresolved += 1
    return unresolved


def blockers(events, dependencies):
    lane_events = defaultdict(list)
    for event in events.values():
        if event["lane_id"]:
            lane_events[event["lane_id"]].append(event)
    idle_from = {}
    for group in lane_events.values():
        end = None
        for event in sorted(group, key=lambda e: (e["start"], e["end"])):
            if end is not None and end < event["start"]:
                idle_from[event["event_id"]] = end
            end = max(end, event["end"]) if end is not None else event["end"]
    matches = defaultdict(list)
    for edge in dependencies:
        source, target = (events[edge[key]] for key in ("source", "target"))
        gap_start = idle_from.get(target["event_id"])
        if (gap_start is None or not source["lane_id"] or source["lane_id"] == target["lane_id"]
                or source["wait_kind"] or target["wait_kind"] or source["end"] > target["start"]
                or not any(row["kind"] in FLOW_KINDS for row in edge["evidence"])):
            continue
        overlap = source["end"] - max(gap_start, source["start"])
        if overlap > 0:
            matches[target["event_id"]].append({
                "source": source["event_id"], "target": target["event_id"], "overlap_cycles": overlap,
                "idle_from": gap_start, "idle_to": target["start"], "producer_end": source["end"],
                "after_producer_cycles": target["start"] - source["end"], "status": "possible",
            })
    # Only the latest finishing recorded cross-lane predecessor can remain the candidate gate.
    candidates = []
    for group in matches.values():
        latest = max(match["producer_end"] for match in group)
        candidates.extend(row for row in group if row["producer_end"] == latest)
    return sorted(candidates, key=lambda row: (-row["overlap_cycles"], row["after_producer_cycles"], row["source"], row["target"]))


def analyze(session, rows, graphs, qhas):
    tracks, cores = physical_tracks(rows)
    reports = qhas_tracks(qhas)
    measured = {operation_key(rows[event.raw_index]): event for event in session.events}
    placements, starts, ends = defaultdict(set), defaultdict(set), defaultdict(set)
    for row in rows:
        key = operation_key(row)
        if not key or key not in measured:
            continue
        pid, tid = row.get("pid"), row.get("tid")
        track = tracks.get((pid, tid))
        if track:
            placements[key].add(track)
        if pid in cores:
            event_id = measured[key].id
            starts[pid, tid, row["ts"]].add(event_id)
            ends[pid, tid, row["ts"] + row["dur"]].add(event_id)

    events, lanes, waits, links, trace_inputs = {}, {}, [], {}, {}
    op_events = defaultdict(list)
    for key, event in measured.items():
        if not key:
            continue
        args = rows[event.raw_index]["args"]
        flags = args.get("Flags", [])
        from_trace = placements[key]
        from_qhas = {track for track, _ in reports[key]}
        available = from_trace | from_qhas
        lane_id = None
        assignment = "conflicting" if len(available) > 1 else "unavailable"
        if len(available) == 1:
            core, kind, tid = next(iter(available))
            lane_id = f"core-{core}-{kind}-tid-{tid}"
            lanes[lane_id] = {"id": lane_id, "core": core, "type": kind, "tid": tid}
            assignment = "trace_and_qhas" if from_trace and from_qhas else "trace" if from_trace else "qhas"
        wait = "dma_wait" if "dma_wait" in flags else "sync" if "sync" in flags else None
        dominant = args.get("Dominant Path Cycles")
        data = {"event_id": event.id, "operation_id": event.operation, "name": event.name,
                "lane_id": lane_id, "assignment": assignment, "qhas_ids": sorted({evidence_id for _, evidence_id in reports[key]}),
                "flags": flags, "start": event.start, "end": event.start + event.duration,
                "wait_kind": wait, "dominant_path_cycles": dominant if finite_number(dominant) else None}
        events[event.id] = data
        trace_inputs[event.id] = args.get("Inputs Ops")
        op_events[key[0]].append(event.id)
        if wait:
            waits.append({"event": event.id, "kind": wait, "cycles": event.duration, "source": "trace_flag"})

    def add(source, target, evidence):
        if source == target:
            return
        row = links.setdefault((source, target), {"source": source, "target": target, "evidence": []})
        if evidence not in row["evidence"]:
            row["evidence"].append(evidence)

    unresolved = trace_edges(rows, cores, starts, ends, add)
    for event_id, inputs in trace_inputs.items():
        for input_operation in inputs if isinstance(inputs, list) else ():
            sources = op_events.get(native_id(input_operation), ())
            if len(sources) == 1:
                add(sources[0], event_id, {"kind": "trace_input", "input_operation": input_operation})
    compiled_edges(graphs, op_events, add)
    dependencies = list(links.values())
    return {
        "profile_id": session.id, "provenance": session.provenance, "unit": "cycles",
        "lanes": sorted(lanes.values(), key=lambda lane: (lane["core"], lane["tid"], lane["type"])),
        "events": events, "dependencies": dependencies, "unresolved_flow_count": unresolved,
        "waits": sorted(waits, key=lambda row: (-row["cycles"], row["event"])), "blockers": blockers(events, dependencies),
        "blocker_scope": "Observed consumer-lane gap overlapping execution of a recorded cross-lane predecessor. Timing overlap does not measure the causal stall or scheduler readiness.",
    }
