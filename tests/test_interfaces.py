import asyncio

from fastapi.testclient import TestClient

from htp_insight import web
from scripts.mcp_smoke import connect
from test_core import local


def test_shared_web_and_mcp(local, monkeypatch):
    core, model_id = local
    a = core.run_ort_profile(model_id, "test.npz", 1, 2, 1)
    b = core.run_ort_profile(model_id, "test.npz", 1, 2, 1)
    comparison = {"baseline": a["id"], "candidate": b["id"]}
    mcp = asyncio.run(connect(core, a["id"], comparison))
    assert mcp["comparison"]["numeric"]["passed"]
    monkeypatch.setattr(web, "core", core)
    client = TestClient(web.app)
    response = client.get(f"/api/profiles/{a['id']}/hotspots")
    assert response.json() == mcp["hotspots"]
    event = mcp["explanation"]["example_evidence"]["id"]
    assert client.get(f"/api/profiles/{a['id']}/events/{event}").json()["raw"]["cat"] == "Node"
    assert client.post("/api/tools/compare_experiments", json=comparison).json() == mcp["comparison"]
    assert client.post("/api/tools/run_ort_profile", json={"model_id": model_id, "inputs": "test.npz", "repeats": "five"}).status_code == 422
    assert client.get(f"/api/experiments/{mcp['comparison']['id']}?format=json").json() == mcp["comparison"]
    assert "Numerical validation" in client.get(f"/api/experiments/{mcp['comparison']['id']}?format=md").text
