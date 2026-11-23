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
        "profile_event": "Read a normalized event and its original JSON or CSV record.",
        "suggest_experiments": "Suggest adaptations and verification metrics for the highest-duration modules.",
        "compare_experiments": "Compare two profile IDs and record graph, latency and numerical differences.",
    }
    for name, method in operations(Core()).items():
        server.add_tool(method, description=descriptions[name], structured_output=True)
    return server


if __name__ == "__main__":
    build_server().run(transport="stdio")
