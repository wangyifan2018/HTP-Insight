from .core import Core

OPERATIONS = (
    "import_model", "inspect_graph", "import_profile", "run_ort_profile", "get_hotspots",
    "explain_hotspot", "suggest_experiments", "compare_experiments",
)


def operations(core: Core):
    return {name: getattr(core, name) for name in OPERATIONS}
