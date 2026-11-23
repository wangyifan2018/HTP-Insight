"""Import the default CSV emitted by QAIRT 2.50 qnn-profile-viewer."""
import csv
import io
import re

import numpy as np

from .schema import NodeMapping, ProfileEvent

HEADER = ["Msg Timestamp", "Message", "Time", "Unit of Measurement", "Timing Source", "Event Level", "Event Identifier"]
OP_ID = re.compile(r"\bOpId_\d+\b")


def csv_rows(raw):
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


class QnnViewerCsvAdapter:
    source = "QNN"
    extension = "csv"

    def parse(self, raw, session, graph):
        rows = csv_rows(raw)
        try:
            header = next(index for index, row in enumerate(rows) if [cell.strip() for cell in row] == HEADER)
        except StopIteration as exc:
            raise ValueError("Expected the QAIRT qnn-profile-viewer CSV event header") from exc
        metadata = {row[0].strip(): row[1].strip() for row in rows[:header] if len(row) == 2}
        version = metadata.get("qnn-profile-viewer version", "")
        if not version.startswith("v2.50."):
            raise ValueError("Expected qnn-profile-viewer 2.50.x CSV")
        session.profiler_version = session.profiler_version or version
        session.conditions["viewer_metadata"] = metadata
        events = []
        operations = set()
        traces = []
        for index, row in enumerate(rows[header + 1:], header + 1):
            if not row:
                continue
            if len(row) != len(HEADER):
                raise ValueError(f"Invalid QAIRT CSV row {index + 1}")
            recorded_at, message, value, unit, timing, level, label = [cell.strip() for cell in row]
            if message != "EXECUTE":
                continue
            matched = OP_ID.search(label) if (unit, timing, level) == ("CYCLES", "BACKEND", "SUB-EVENT") else None
            if matched:
                operation = matched[0]
                operations.add(operation)
                kind = "node"
            elif (unit, timing, level) == ("US", "NETRUN", "ROOT"):
                operation = None
                kind = "inference"
            else:
                continue
            try:
                timestamp, duration = int(recorded_at), int(value)
            except ValueError as exc:
                raise ValueError(f"Invalid QAIRT execute timing at CSV row {index + 1}") from exc
            if timestamp < 0 or duration < 0:
                raise ValueError(f"Negative QAIRT execute timing at CSV row {index + 1}")
            if kind == "inference":
                traces.append((timestamp, label, duration))
            events.append(ProfileEvent(
                id=f"{session.id}-e{index}", operation=operation, name=label, kind=kind, source=self.source,
                backend=session.backend, device=session.device, profiler_version=session.profiler_version,
                duration=duration, unit="cycles" if matched else "us",
                recorded_timestamp_us=timestamp, raw_index=index,
            ))
        if not events:
            raise ValueError("QAIRT CSV contains no supported execute rows")
        session.events = events
        session.unit = "cycles" if operations else "us"
        session.mappings = [NodeMapping(operation_ids=[op], node_ids=[], method="unknown") for op in sorted(operations)]
        if len({name for _, name, _ in traces}) == 1:
            discard = session.conditions.get("warmup", 0)
            if type(discard) is not int or not 0 <= discard < len(traces):
                raise ValueError("CSV warmup must be a nonnegative count smaller than the number of executions")
            samples = [item[2] for item in sorted(traces, key=lambda item: item[0])][discard:]
            session.latency_us = {
                "p50": float(np.percentile(samples, 50)), "p95": float(np.percentile(samples, 95)),
                "samples": samples, "scope": "qnn-profile-viewer CSV EXECUTE/NETRUN/ROOT, single graph",
                "label": "NetRun graph execute (QAIRT CSV)",
            }
            session.conditions.setdefault("warmup", discard)
            session.conditions.setdefault("repeats", len(samples))
