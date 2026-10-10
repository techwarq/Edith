from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from edith.memory import db
from edith.memory import startup_leads_store as leads_store
from edith.startup_finder import api, finder

TOKEN = "t"


def _client(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    settings = SimpleNamespace(hunter_api_key="", crustdata_api_key="", gemini_grounding_model="m")
    monkeypatch.setattr(finder, "crawl", lambda on_progress=None: ([
        {"kind": "founder", "dedup_key": f"co:{i}.ai", "company": f"Co{i}", "domain": f"{i}.ai", "region": "europe",
         "description": "AI video", "team_size": 20} for i in range(30)
    ], {"sources": {}, "errors": {}}))
    app = FastAPI()
    app.include_router(api.build_router(conn, settings, None, TOKEN))
    return TestClient(app), conn


def test_run_requires_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.post("/api/startup-finder/run", json={"count": 3}).status_code == 401


def test_run_returns_exact_count(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    r = client.post("/api/startup-finder/run", json={"token": TOKEN, "count": 7})
    assert r.status_code == 200
    assert r.json()["returned"] == 7
    r2 = client.post("/api/startup-finder/run", json={"token": TOKEN, "count": 7})
    assert not {l["id"] for l in r.json()["leads"]} & {l["id"] for l in r2.json()["leads"]}


def test_run_validates_kind(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.post("/api/startup-finder/run", json={"token": TOKEN, "kind": "x"}).status_code == 400


def test_list_and_patch_lead(tmp_path, monkeypatch):
    client, conn = _client(tmp_path, monkeypatch)
    lead_id = client.post("/api/startup-finder/run", json={"token": TOKEN, "count": 1}).json()["leads"][0]["id"]
    listed = client.get("/api/startup-finder/leads", params={"token": TOKEN, "status": "delivered"}).json()
    assert [l["id"] for l in listed["leads"]] == [lead_id]
    r = client.patch(f"/api/startup-finder/leads/{lead_id}", json={"token": TOKEN, "status": "contacted"})
    assert r.json()["status"] == "contacted"
    assert client.patch(f"/api/startup-finder/leads/{lead_id}", json={"token": TOKEN, "status": "bogus"}).status_code == 400
    assert client.patch("/api/startup-finder/leads/999", json={"token": TOKEN, "status": "skipped"}).status_code == 404
