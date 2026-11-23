import inspect

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .core import ROOT, Core
from .interfaces import operations

core = Core()
app = FastAPI(title="HTP Insight")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])


def call(method, *args, **kwargs):
    try:
        return method(*args, **kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Artifact or evidence unavailable") from exc
    except (ValueError, TypeError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/catalog")
def catalog():
    return core.catalog()


@app.get("/api/models/{model_id}/graph")
def model_graph(model_id: str):
    return call(core.inspect_graph, model_id)


@app.get("/api/profiles/{profile_id}")
def profile(profile_id: str):
    return call(core.profile, profile_id)


@app.get("/api/profiles/{profile_id}/hotspots")
def hotspots(profile_id: str, level: str = "module", limit: int = 10):
    return call(core.get_hotspots, profile_id, level, limit)


@app.get("/api/profiles/{profile_id}/hotspots/{hotspot_id}")
def explanation(profile_id: str, hotspot_id: str, level: str = "module"):
    return call(core.explain_hotspot, profile_id, hotspot_id, level)


@app.get("/api/profiles/{profile_id}/raw")
def raw_trace(profile_id: str):
    session = call(core.session, profile_id)
    extension = session.raw_format
    path = call(core.item, profile_id, f"trace.{extension}")
    if not path.is_file():
        raise HTTPException(404, "Raw trace unavailable")
    return FileResponse(path, media_type="text/csv" if extension == "csv" else "application/json",
                        filename=f"{profile_id}.{extension}")


@app.get("/api/profiles/{profile_id}/events/{event_id}")
def raw_event(profile_id: str, event_id: str):
    return call(core.profile_event, profile_id, event_id)


@app.get("/api/experiments/{experiment_id}")
def experiment(experiment_id: str, format: str | None = None):
    if format == "md":
        return PlainTextResponse(call(core.report, experiment_id), headers={
            "Content-Disposition": f'attachment; filename="{experiment_id}.md"',
        })
    if format == "json":
        result = call(core.item, experiment_id, "experiment.json")
        if not result.is_file():
            raise HTTPException(404, "Experiment unavailable")
        return FileResponse(result, filename=f"{experiment_id}.json", media_type="application/json")
    return call(core.read, experiment_id, "experiment.json")


@app.post("/api/tools/{operation}")
def run_tool(operation: str, arguments: dict):
    method = operations(core).get(operation)
    if method is None:
        raise HTTPException(404, "Unknown operation")
    signature = inspect.signature(method)
    values = call(signature.bind, **arguments)
    typed = {key: call(TypeAdapter(signature.parameters[key].annotation).validate_python, value, strict=True)
             for key, value in values.arguments.items()}
    try:
        return call(method, **typed)
    except HTTPException:
        raise
    except Exception as exc:
        # Native ONNX and ORT bindings expose their own exception classes.
        raise HTTPException(422, str(exc)) from exc


dist = ROOT / "web/dist"
app.mount("/assets", StaticFiles(directory=dist / "assets", check_dir=False), name="assets")


@app.get("/")
def index():
    home = dist / "index.html"
    return FileResponse(home) if home.is_file() else Response("Build the Web UI with make web.", status_code=503)
