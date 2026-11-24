from .core import Core

OPERATIONS = (
    "import_model", "inspect_graph", "import_profile", "run_ort_profile", "get_hotspots",
    "explain_hotspot", "profile_event", "import_evidence", "profile_evidence", "suggest_experiments", "compare_experiments",
    "analyze_model_performance", "generate_experiment_plan", "inspect_htp_timeline",
)


def operations(core: Core):
    return {name: getattr(core, name) for name in OPERATIONS}
