from mcp.server.fastmcp import FastMCP

from .core import Core
from .interfaces import operations


def build_server():
    server = FastMCP("HTP Insight", instructions="Local ONNX/ORT evidence and optional imported traces. "
                     "Inspect source, provenance, backend and conditions before making performance claims.")
    descriptions = {
        "import_model": "Register an ONNX or HTP .bin from the inbox. Optional AIMET encodings for ONNX.",
        "inspect_graph": "Inspect dependencies, semantic modules, inferred tensors and quantization.",
        "import_profile": "Import inbox profiles using qnn-viewer-csv-v2.50 or ort-chrome-v1, optrace-chrome-v1, qnn-linting-chrome-v2.50, or qnn-optrace-chrome-v2.50. Optional DLC framework CSV resolves Optrace names to source ONNX nodes. Declare fixture provenance when applicable.",
        "run_ort_profile": "Run a bounded local ORT CPU benchmark using a registered model and inbox NPZ.",
        "get_hotspots": "Rank nodes or modules by operation trace duration. Includes evidence IDs and deep links.",
        "explain_hotspot": "Return graph tensors, quantization, raw evidence and a falsifiable hypothesis.",
        "import_evidence": "Attach QAIRT QHAS 1.0 or HTP Graph 1.0 JSON to a registered profile.",
        "profile_evidence": "List QHAS and HTP Graph attachments, optionally matched to an HTP operation ID.",
        "profile_event": "Read a normalized event and its original JSON or CSV record.",
        "suggest_experiments": "Suggest adaptations and verification metrics for the highest-duration modules.",
        "compare_experiments": "Compare two profile IDs and record graph, latency and numerical differences.",
        "analyze_model_performance": "Read a profile's source model, observed graph latency, ranked hotspots, evidence gaps and the next Notebook experiment in one call.",
        "generate_experiment_plan": "Create a Notebook adaptation task with observed evidence, shapes, mapping, a hypothesis, numerical checks and matched A/B criteria. Returns structured JSON and Markdown.",
    }
    for name, method in operations(Core()).items():
        server.add_tool(method, description=descriptions[name], structured_output=True)
    return server


if __name__ == "__main__":
    build_server().run(transport="stdio")
