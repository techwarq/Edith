from fastapi import FastAPI
from fastapi.testclient import TestClient

from edith.goals import api as goals_api
from edith.memory import db, goals_store

TOKEN = "test-token"


def _client(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    router = goals_api.build_router(conn, TOKEN)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), conn


def test_list_goals_requires_token(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/goals")
    assert resp.status_code == 401


def test_create_and_list_goal(tmp_path):
    client, _ = _client(tmp_path)

    create_resp = client.post("/api/goals", json={"token": TOKEN, "title": "Ship v2", "target_date": "2026-08-01"})
    assert create_resp.status_code == 200
    assert create_resp.json()["title"] == "Ship v2"

    list_resp = client.get("/api/goals", params={"token": TOKEN})
    assert list_resp.status_code == 200
    assert len(list_resp.json()["goals"]) == 1


def test_create_goal_requires_title(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/api/goals", json={"token": TOKEN, "title": "  "})
    assert resp.status_code == 400


def test_get_goal_not_found(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/goals/999", params={"token": TOKEN})
    assert resp.status_code == 404


def test_update_goal_status(tmp_path):
    client, conn = _client(tmp_path)
    goal_id = goals_store.create_goal(conn, "Goal")

    resp = client.post(f"/api/goals/{goal_id}/update", json={"token": TOKEN, "status": "done"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


def test_update_goal_not_found(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/api/goals/999/update", json={"token": TOKEN, "status": "done"})
    assert resp.status_code == 404


def test_delete_goal(tmp_path):
    client, conn = _client(tmp_path)
    goal_id = goals_store.create_goal(conn, "Goal")

    resp = client.post(f"/api/goals/{goal_id}/delete", json={"token": TOKEN})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert goals_store.get_goal(conn, goal_id) is None


def test_add_and_complete_milestone(tmp_path):
    client, conn = _client(tmp_path)
    goal_id = goals_store.create_goal(conn, "Goal")

    add_resp = client.post(f"/api/goals/{goal_id}/milestones", json={"token": TOKEN, "title": "step 1"})
    assert add_resp.status_code == 200
    milestone_id = add_resp.json()["id"]

    complete_resp = client.post(f"/api/milestones/{milestone_id}/complete", json={"token": TOKEN})
    assert complete_resp.status_code == 200
    assert complete_resp.json()["ok"] is True

    goal = goals_store.get_goal(conn, goal_id)
    assert goal["milestones"][0]["done"] == 1


def test_add_milestone_to_missing_goal(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/api/goals/999/milestones", json={"token": TOKEN, "title": "step"})
    assert resp.status_code == 404


def test_insights_list_and_dismiss(tmp_path):
    client, conn = _client(tmp_path)
    goals_store.add_insight(conn, "Something worth knowing")

    list_resp = client.get("/api/insights", params={"token": TOKEN})
    assert list_resp.status_code == 200
    insights = list_resp.json()["insights"]
    assert len(insights) == 1
    insight_id = insights[0]["id"]

    dismiss_resp = client.post(f"/api/insights/{insight_id}/dismiss", json={"token": TOKEN})
    assert dismiss_resp.status_code == 200
    assert dismiss_resp.json()["ok"] is True

    unseen_resp = client.get("/api/insights", params={"token": TOKEN})
    assert unseen_resp.json()["insights"] == []
