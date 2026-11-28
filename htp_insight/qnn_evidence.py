"""Structured QAIRT HTP Graph and QHAS exports, with raw evidence retained by Core."""
import re
from collections import Counter

ARTIFACT_TYPES = {
    "qhas-v1.0": "QHAS",
    "htp-graph-v1.0": "HTP_GRAPH",
}


def native_id(value):
    if isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]+", value):
        return hex(int(value, 16))
    return None


def rows(section):
    data = section.get("data") if isinstance(section, dict) else None
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError("Invalid QAIRT data table")
    return data


def parse_evidence(document, format):
    if format not in ARTIFACT_TYPES:
        raise ValueError(f"Supported evidence formats: {', '.join(ARTIFACT_TYPES)}")
    header = document.get("header") if isinstance(document, dict) else None
    if not isinstance(header, dict) or header.get("artifact_type") != ARTIFACT_TYPES[format]:
        raise ValueError(f"Expected QAIRT {ARTIFACT_TYPES[format]} artifact")
    version = header.get("version")
    if not isinstance(version, dict) or (version.get("major"), version.get("minor")) != (1, 0):
        raise ValueError("Expected QAIRT artifact schema 1.0")
    summary, operations = qhas(document) if format == "qhas-v1.0" else htp_graph(document)
    return {"artifact_type": header["artifact_type"], "schema_version": version, "summary": summary}, operations


def qhas(document):
    data = document.get("data")
    if not isinstance(data, dict):
        raise ValueError("QHAS artifact is missing data tables")
    operation_rows = rows(data.get("htp_op_instances"))
    cores, resources = [], []
    for row in rows(data.get("htp_overall_summary")):
        cores.append({key: row.get(key) for key in (
            "htp", "timeline_cycles", "percent_idle", "percent_utilization", "graph_execute_us",
            "total_dram_read", "total_dram_write", "peak_vtcm_alloc", "mac_estimate_whole_graph",
        )})
        if row.get("htp_resources") is not None:
            resources.extend({"core": row.get("htp"), **{key: item.get(key) for key in (
                "type", "tid", "timeline_cycles", "cycles_used", "utilization", "dram_read", "dram_write",
            )}} for item in rows(row["htp_resources"]))
    operations = {}
    for row in operation_rows:
        identifier = native_id(row.get("op_id"))
        if identifier is not None:
            operations.setdefault(identifier, []).append({key: row.get(key) for key in (
                "op_id", "htp", "tid", "htp_op", "qnn_op", "qnn_op_type", "dtype", "dims", "start_cycle", "cycles",
                "num_dominant_path_cycles", "dram_read", "dram_write", "vtcm_read", "vtcm_write",
            )})
    summary = {"model_id": document.get("model_id"), "cores": cores, "resources": resources,
               "operation_count": len(operation_rows)}
    return summary, operations


def htp_graph(document):
    graph = document.get("graph")
    if not isinstance(graph, dict):
        raise ValueError("HTP graph artifact is missing a graph")
    nodes, tensors = graph.get("nodes"), graph.get("tensors")
    if any(not isinstance(table, dict) or any(not isinstance(row, dict) for row in table.values())
           for table in (nodes, tensors)):
        raise ValueError("Expected HTP graph node and tensor dictionaries")
    operators = Counter()
    operations = {}
    for key, node in nodes.items():
        label = node.get("type")
        if not isinstance(label, str):
            raise ValueError(f"HTP graph node {key} is missing its operation type")
        operators[label] += 1
        identifier = native_id(key)
        if identifier is not None:
            operations.setdefault(identifier, []).append({
                "op_id": key, "htp_op": label, "qnn_group": node.get("grouping"),
                "input_tensors": node.get("input_names"), "output_tensors": node.get("output_names"),
            })
    return {"node_count": len(nodes), "tensor_count": len(tensors),
            "operator_types": dict(sorted(operators.items()))}, operations
