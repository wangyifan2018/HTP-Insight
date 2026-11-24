"""Evidence-based resource, dependency, and wait analysis for QAIRT Optrace."""

from collections import defaultdict
import re
from urllib.parse import quote

from .profiles import finite_number
from .qnn_evidence import native_id

OVERVIEW = re.compile(r"Core\s+(\d+)\s+Overview", re.IGNORECASE)
THREAD = re.compile(r"(?:Core:\s*(\d+)\s+)?Type:\s*([\w./-]+)(?:\s+Tid:\s*(\d+))?", re.IGNORECASE)
FLOWS = {"input_output": "trace_data", "sequencer": "trace_sequencer"}
FLOW_KINDS = frozenset(FLOWS.values())


def operation_key(row):
    if not isinstance(row, dict):
        return None
    args = row.get("args", {})
    if row.get("ph") == "X" and isinstance(args, dict) and "Start Cycle" in args and "Duration (cycles)" in args:
        identifier = native_id(args.get("ID"))
        if identifier and isinstance(args["Start Cycle"], (int, float)) and isinstance(args["Duration (cycles)"], (int, float)):
            return identifier, args["Start Cycle"], args["Duration (cycles)"]
    return None


def trace_tracks(rows):
    cores, labels = defaultdict(set), defaultdict(list)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        args = row.get("args")
        if row.get("ph") != "M" or not isinstance(args, dict) or not isinstance(args.get("name"), str):
            continue
        pid, tid, name = row.get("pid"), row.get("tid"), args["name"]
        if not isinstance(pid, int):
            continue
        if row.get("name") == "process_name" and (match := OVERVIEW.fullmatch(name)):
            cores[pid].add(int(match[1]))
        if row.get("name") == "thread_name" and isinstance(tid, int):
            labels[pid, tid].append((index, name))
    tracks = defaultdict(list)
    for (pid, tid), metadata in labels.items():
        for index, name in metadata:
            if not (match := THREAD.fullmatch(name.strip())):
                continue
            explicit_core, kind, explicit_tid = match.groups()
            if explicit_tid is not None and tid != int(explicit_tid):
                continue
            core_ids = {int(explicit_core)} if explicit_core is not None else cores[pid] or {None}
            for core in core_ids:
                track = (core, kind.upper(), tid, pid if core is None else None)
                tracks[pid, tid].append((track, {"pid": pid, "tid": tid, "name": name, "raw_index": index}))
    return tracks, cores, labels


def qhas_tracks(attachments):
    assignments = defaultdict(set)
    declared = defaultdict(set)
    for evidence_id, tables in attachments:
        types = defaultdict(set)
        for core in tables.get("htp_overall_summary", {}).get("data", []):
            core_id = core.get("htp")
            if not isinstance(core_id, int):
                continue
            for row in (core.get("htp_resources") or {}).get("data", []):
                tid = row.get("tid")
                kind = row.get("type")
                if isinstance(tid, int) and isinstance(kind, str) and kind.strip():
                    track = (core_id, kind.strip().upper(), tid, None)
                    types[core_id, tid].add(track)
                    declared[track].add(evidence_id)
        for row in tables.get("htp_op_instances", {}).get("data", []):
            core, tid = row.get("htp"), row.get("tid")
            start, cycles = row.get("start_cycle"), row.get("cycles")
            if not isinstance(core, int) or not isinstance(tid, int) or not finite_number(start) or not finite_number(cycles):
                continue
            identifier = native_id(row.get("op_id"))
            if identifier:
                assignments[identifier, start, cycles].update((track, evidence_id) for track in types[core, tid])
    return assignments, declared


def lane_id(track):
    core, kind, tid, pid = track
    scope = f"core-{core}" if core is not None else f"pid-{pid}"
    return f"{scope}-{quote(kind, safe='') if kind else 'untyped'}-tid-{tid}"


def resolve_track(trace, reports):
    candidates = trace | reports
    known = {track for track in candidates if track[0] is not None}
    if len(known) == 1:
        _, kind, tid, _ = next(iter(known))
        # A core-less copy can corroborate the type/TID but cannot supply a core.
        candidates = known | {track for track in candidates - known if track[1:3] != (kind, tid)}
    if len(candidates) != 1:
        return None, "conflicting" if candidates else "unavailable", candidates
    track = next(iter(candidates))
    via_trace = track in trace or any(item[0] is None and item[1:3] == track[1:3] for item in trace)
    via_qhas = track in reports
    return track, "trace_and_qhas" if via_trace and via_qhas else "trace" if via_trace else "qhas", candidates


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


def trace_edges(rows, eligible_pids, starts, ends, add):
    flows = defaultdict(lambda: defaultdict(list))
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        phase, category, flow_id = row.get("ph"), row.get("cat"), row.get("id")
        if (phase in ("s", "f") and isinstance(category, str) and category in FLOWS
                and isinstance(flow_id, (int, str)) and isinstance(row.get("pid"), int) and row["pid"] in eligible_pids
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


def blockers(events, dependencies, lanes):
    lane_events = defaultdict(list)
    for event in events.values():
        if event["lane_id"] and lanes[event["lane_id"]]["core"] is not None:
            lane_events[event["lane_id"]].append(event)
    idle_from = {}
    for group in lane_events.values():
        end = None
        for event in sorted(group, key=lambda e: (e["start"], e["end"])):
            if end is not None and end < event["start"]:
                idle_from[event["event_id"]] = end
            end = max(end, event["end"]) if end is not None else event["end"]
    predecessors = []
    latest_finish = {}
    for edge in dependencies:
        source, target = (events[edge[key]] for key in ("source", "target"))
        if source["end"] <= target["start"] and any(row["kind"] in FLOW_KINDS for row in edge["evidence"]):
            target_id = target["event_id"]
            latest_finish[target_id] = max(latest_finish.get(target_id, source["end"]), source["end"])
            predecessors.append((source, target))
    candidates = []
    for source, target in predecessors:
        gap_start = idle_from.get(target["event_id"])
        if (gap_start is None or not source["lane_id"] or source["lane_id"] == target["lane_id"]
                or lanes[source["lane_id"]]["core"] != lanes[target["lane_id"]]["core"]
                or source["wait_kind"] or target["wait_kind"] or source["end"] < latest_finish[target["event_id"]]):
            continue
        overlap = source["end"] - max(gap_start, source["start"])
        if overlap > 0:
            candidates.append({
                "source": source["event_id"], "target": target["event_id"], "overlap_cycles": overlap,
                "idle_from": gap_start, "idle_to": target["start"], "producer_end": source["end"],
                "after_producer_cycles": target["start"] - source["end"], "status": "possible",
            })
    return sorted(candidates, key=lambda row: (-row["overlap_cycles"], row["after_producer_cycles"], row["source"], row["target"]))


def analyze(session, rows, graphs, qhas):
    tracks, cores, raw_labels = trace_tracks(rows)
    reports, declared = qhas_tracks(qhas)
    lanes = {}

    def register(track):
        identifier = lane_id(track)
        if identifier not in lanes:
            core, kind, tid, pid = track
            lanes[identifier] = {"id": identifier, "core": core, "type": kind, "tid": tid, "pid": pid,
                                 "trace_tracks": [], "qhas_ids": [], "event_count": 0}
        return lanes[identifier]

    for details in tracks.values():
        for track, record in details:
            register(track)["trace_tracks"].append(record)
    for track, ids in declared.items():
        register(track)["qhas_ids"] = sorted(ids)

    overview_cores = set().union(*cores.values())
    eligible_pids = {pid for pid, core_ids in cores.items() if core_ids}
    eligible_pids.update(pid for (pid, _), details in tracks.items()
                         if any(track[0] not in overview_cores for track, _ in details))
    measured = {operation_key(rows[event.raw_index]): event for event in session.events}
    placements, starts, ends = defaultdict(set), defaultdict(set), defaultdict(set)
    for row in rows:
        key = operation_key(row)
        if not key or key not in measured:
            continue
        pid, tid = row.get("pid"), row.get("tid")
        placements[key].update(track for track, _ in tracks.get((pid, tid), ()))
        if pid in eligible_pids and finite_number(row.get("ts")) and finite_number(row.get("dur")):
            event_id = measured[key].id
            starts[pid, tid, row["ts"]].add(event_id)
            ends[pid, tid, row["ts"] + row["dur"]].add(event_id)

    events, waits, links, trace_inputs = {}, [], {}, {}
    reconciled = set()
    op_events = defaultdict(list)
    for key, event in measured.items():
        if not key:
            continue
        raw = rows[event.raw_index]
        args = raw["args"]
        flags = args.get("Flags", [])
        from_trace = placements[key]
        from_qhas = {track for track, _ in reports[key]}
        track, assignment, candidates = resolve_track(from_trace, from_qhas)
        pid, tid = raw.get("pid"), raw.get("tid")
        if assignment == "unavailable" and isinstance(pid, int) and isinstance(tid, int):
            track, assignment = (None, None, tid, pid), "unclassified_track"
        lane = register(track) if track is not None else None
        if lane:
            lane["event_count"] += 1
            if assignment == "unclassified_track" and not lane["trace_tracks"]:
                lane["trace_tracks"].extend({"pid": pid, "tid": tid, "name": name, "raw_index": index}
                                            for index, name in raw_labels[pid, tid])
            for trace_track in from_trace - {track}:
                if trace_track[0] is None and (track, trace_track) not in reconciled:
                    lane["trace_tracks"].extend(lanes[lane_id(trace_track)]["trace_tracks"])
                    reconciled.add((track, trace_track))
        wait = "dma_wait" if "dma_wait" in flags else "sync" if "sync" in flags else None
        dominant = args.get("Dominant Path Cycles")
        data = {"event_id": event.id, "operation_id": event.operation, "name": event.name,
                "lane_id": lane["id"] if lane else None, "assignment": assignment,
                "candidate_lanes": sorted(lane_id(candidate) for candidate in candidates),
                "qhas_ids": sorted({evidence_id for _, evidence_id in reports[key]}),
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

    unresolved = trace_edges(rows, eligible_pids, starts, ends, add)
    for event_id, inputs in trace_inputs.items():
        for input_operation in inputs if isinstance(inputs, list) else ():
            sources = op_events.get(native_id(input_operation), ())
            if len(sources) == 1:
                add(sources[0], event_id, {"kind": "trace_input", "input_operation": input_operation})
    compiled_edges(graphs, op_events, add)
    dependencies = list(links.values())
    return {
        "profile_id": session.id, "provenance": session.provenance, "unit": "cycles",
        "lanes": sorted(lanes.values(), key=lambda lane: (lane["core"] is None, lane["core"] or 0,
                                                         lane["tid"], lane["type"] or "", lane["id"])),
        "events": events, "dependencies": dependencies, "unresolved_flow_count": unresolved,
        "waits": sorted(waits, key=lambda row: (-row["cycles"], row["event"])), "blockers": blockers(events, dependencies, lanes),
        "blocker_scope": "Timing overlap between an observed consumer-lane gap and a recorded cross-lane predecessor on the same identified core. Causal stall duration and scheduler readiness are unknown.",
    }
