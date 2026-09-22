from fastapi import FastAPI
from fastapi.testclient import TestClient

from edith.job_applications import api as job_applications_api
from edith.memory import db, job_applications_store as jobs_store, store
from edith.tools.job_applications import AUTONOMOUS_KEY

TOKEN = "test-token"


def _client(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    router = job_applications_api.build_router(conn, TOKEN)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), conn


def test_list_job_applications_requires_token(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/job-applications")
    assert resp.status_code == 401


def test_list_and_get_job_application(tmp_path):
    client, conn = _client(tmp_path)
    app_id = jobs_store.create_lead(conn, "Acme Inc", company_domain="acme.com", role_title="Engineer")

    list_resp = client.get("/api/job-applications", params={"token": TOKEN})
    assert list_resp.status_code == 200
    assert len(list_resp.json()["applications"]) == 1

    get_resp = client.get(f"/api/job-applications/{app_id}", params={"token": TOKEN})
    assert get_resp.status_code == 200
    assert get_resp.json()["company"] == "Acme Inc"


def test_get_job_application_not_found(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/job-applications/999", params={"token": TOKEN})
    assert resp.status_code == 404


def test_approve_without_pending_action_returns_404(tmp_path):
    client, conn = _client(tmp_path)
    app_id = jobs_store.create_lead(conn, "Acme Inc", company_domain="acme.com")

    resp = client.post(f"/api/job-applications/{app_id}/approve", json={"token": TOKEN})
    assert resp.status_code == 404


def test_approve_sends_email_and_updates_status(tmp_path, monkeypatch):
    client, conn = _client(tmp_path)
    app_id = jobs_store.create_lead(conn, "Acme Inc", company_domain="acme.com")
    action_id = store.queue_pending_action(
        conn, tool_name="send_email", args={"to": "founder@acme.com", "subject": "Hi", "body": "Hello"},
        preview="preview",
    )
    jobs_store.update_application(conn, app_id, status="queued_for_approval", pending_action_id=action_id)

    monkeypatch.setitem(job_applications_api.EXECUTORS, "send_email", lambda creds, args: f"Email sent to {args['to']}.")
    monkeypatch.setattr(job_applications_api.google_auth, "get_credentials", lambda: object())

    resp = client.post(f"/api/job-applications/{app_id}/approve", json={"token": TOKEN})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "sent"
    assert store.get_pending_actions(conn, status="pending") == []


def test_reject_marks_failed_without_sending(tmp_path, monkeypatch):
    client, conn = _client(tmp_path)
    app_id = jobs_store.create_lead(conn, "Acme Inc", company_domain="acme.com")
    action_id = store.queue_pending_action(
        conn, tool_name="send_email", args={"to": "founder@acme.com", "subject": "Hi", "body": "Hello"},
        preview="preview",
    )
    jobs_store.update_application(conn, app_id, status="queued_for_approval", pending_action_id=action_id)

    def fail_if_called(*a, **k):
        raise AssertionError("reject must never call an executor")
    monkeypatch.setitem(job_applications_api.EXECUTORS, "send_email", fail_if_called)

    resp = client.post(f"/api/job-applications/{app_id}/reject", json={"token": TOKEN})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error"] == "rejected by user"


def test_jobs_config_get_and_set(tmp_path):
    client, conn = _client(tmp_path)

    initial = client.get("/api/jobs-config", params={"token": TOKEN})
    assert initial.status_code == 200
    assert initial.json()["autonomous_enabled"] is False

    set_resp = client.post("/api/jobs-config", json={"token": TOKEN, "autonomous_enabled": True})
    assert set_resp.status_code == 200
    assert set_resp.json()["autonomous_enabled"] is True
    assert store.get_fact(conn, AUTONOMOUS_KEY) == "true"
