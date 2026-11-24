import asyncio

from fastapi.testclient import TestClient

from htp_insight import web
from scripts.mcp_smoke import connect
from test_core import fixture_profile, local


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
    status = client.get("/api/capabilities").json()
    assert status["ort_cpu_available"]
    assert status["examples"][0]["experiment_id"] == mcp["comparison"]["id"]
    event = mcp["explanation"]["example_evidence"]["id"]
    assert client.get(f"/api/profiles/{a['id']}/events/{event}").json()["raw"]["cat"] == "Node"
    assert client.post("/api/tools/compare_experiments", json=comparison).json() == mcp["comparison"]
    assert client.post("/api/tools/run_ort_profile", json={"model_id": model_id, "inputs": "test.npz", "repeats": "five"}).status_code == 422
    assert client.get(f"/api/experiments/{mcp['comparison']['id']}?format=json").json() == mcp["comparison"]
    assert "Numerical validation" in client.get(f"/api/experiments/{mcp['comparison']['id']}?format=md").text
    plan = mcp["plan"]
    path = f"/api/profiles/{a['id']}/hotspots/{plan['hotspot']['id']}/plan"
    assert client.get(path).json() == plan
    assert client.get(path + "?format=json").json() == plan
    assert client.get(path + "?format=md").text == plan["markdown"]
    assert mcp["overview"]["next_experiment"] == plan
    assert plan["evidence"][0]["event"]["id"] in plan["hotspot"]["evidence_ids"]
    fixture = fixture_profile(core, model_id)
    first = core.get_hotspots(fixture["id"])["hotspots"][0]["id"]
    assert client.get(f"/api/profiles/{fixture['id']}/hotspots/{first}/plan").status_code == 422
    assert core.analyze_model_performance(fixture["id"])["next_experiment"] is None
    assert fixture["id"] not in {item["id"] for item in client.get("/api/capabilities").json()["measured_captures"]}
    compact = client.get("/api/catalog?compact=true").json()
    assert "samples" not in next(p for p in compact["profiles"] if p["id"] == a["id"])["latency_us"]
    assert core.profile(a["id"])["latency_us"]["samples"]
    named = client.post("/api/tools/compare_experiments", json={**comparison, "name": "Local quality"}).json()
    assert named["name"] == "Local quality" and named["id"] != mcp["comparison"]["id"]


def test_local_upload_and_compiled_binding(local, monkeypatch):
    core, model_id = local
    monkeypatch.setattr(web, "core", core)
    client = TestClient(web.app)
    dest = "/api/inbox/" + "9" * 32 + "/nested/fixture.bin"
    headers = {"Content-Type": "application/octet-stream", "Origin": "http://testserver"}
    assert client.post(dest, headers={**headers, "Origin": "https://example.org"}, content=b"blocked").status_code == 403
    staged = client.post(dest, headers=headers, content=b"fixture context")
    assert staged.status_code == 200
    result = client.post("/api/tools/import_model", json={"filename": staged.json()["filename"], "source_model_id": model_id,
                                                         "target_device": "SM6650", "compatibility": {"hexagon": "v73"}})
    assert result.status_code == 200
    artifact = result.json()["artifact"]
    assert artifact["source_model_id"] == model_id and artifact["format"] == "HTP_CONTEXT"
    assert core.item(artifact["id"], "context.bin").read_bytes() == b"fixture context"
    assert client.post(dest, headers=headers, content=b"replacement").status_code == 409
    assert client.post("/api/android/captures", json={"artifact_id": artifact["id"], "inputs": {}}).status_code == 422
