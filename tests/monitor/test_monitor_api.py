from fastapi import FastAPI
from fastapi.testclient import TestClient

from edith.config import Settings
from edith.memory import db, ideas_bugs_store, store
from edith.monitor import api as monitor_api
from edith.monitor import dodo, github_shipping, vercel_analytics
from edith.tools.ops.monitor import SHIPPING_ACCOUNT_CATEGORY, SHIPPING_REPO_CATEGORY, VERCEL_PROJECT_CATEGORY
from edith.tools.growth.social import SOCIAL_SKILL_CATEGORY

TOKEN = "test-token"


def _settings(tmp_path, **overrides):
    base = dict(
        api_key="k",
        model="m",
        gemini_api_key="k",
        gemini_grounding_model="gm",
        openrouter_text_model="otm",
        db_path=tmp_path / "edith.db",
        log_path=tmp_path / "edith.log",
        history_path=tmp_path / "history",
        stt_model="stt",
        tts_model="tts",
        tts_voice="voice",
        qdrant_url="",
        qdrant_api_key="",
        temporal_address="",
        temporal_namespace="",
        temporal_api_key="",
        temporal_task_queue="q",
        nightly_reflection_cron="0 3 * * *",
        firebase_service_account_json="",
        hunter_api_key="",
        dodo_payments_api_key="",
        dodo_payments_base_url="https://live.dodopayments.com",
        vercel_analytics_token="",
        vercel_team_id="",
        github_token="",
        linkedin_text_model="ltm",
        linkedin_fallback_text_model="lftm",
        linkedin_image_model="lim",
        linkedin_fallback_image_model="lfim",
        linkedin_client_id="",
        linkedin_client_secret="",
        linkedin_redirect_uri="",
        linkedin_version="202607",
        database_url="",
        pgvector_enabled=True,
        computer_use_writer_model="cuwm",
        computer_use_max_steps=12,
        computer_use_confidence_threshold=0.5,
    )
    base.update(overrides)
    return Settings(**base)


def _client(tmp_path, **settings_overrides):
    conn = db.connect(tmp_path / "test.db")
    settings = _settings(tmp_path, **settings_overrides)
    router = monitor_api.build_router(conn, settings, genai_client=object(), api_token=TOKEN)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), conn


def test_requires_token(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/api/monitor/revenue").status_code == 401
    assert client.get("/api/monitor/ideas-bugs").status_code == 401


def test_revenue_not_configured(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/monitor/revenue", params={"token": TOKEN})
    assert resp.json() == {"configured": False}


def test_revenue_configured(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, dodo_payments_api_key="real-key")
    monkeypatch.setattr(
        dodo,
        "get_revenue_summary",
        lambda base_url, api_key: {"configured": True, "gross_revenue_usd": 100.0, "mrr_usd": 10.0, "net_revenue_usd": 90.0, "last_payment": None},
    )
    resp = client.get("/api/monitor/revenue", params={"token": TOKEN})
    assert resp.json()["gross_revenue_usd"] == 100.0


def test_revenue_error_surfaces_as_502(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, dodo_payments_api_key="real-key")

    def raise_err(base_url, api_key):
        raise dodo.DodoError("boom")

    monkeypatch.setattr(dodo, "get_revenue_summary", raise_err)
    resp = client.get("/api/monitor/revenue", params={"token": TOKEN})
    assert resp.status_code == 502
    assert resp.json()["error"] == "boom"


def test_analytics_not_configured_with_no_token_or_projects(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/monitor/analytics", params={"token": TOKEN})
    assert resp.json() == {"configured": False, "projects": []}


def test_analytics_not_configured_when_token_set_but_no_projects_tracked(tmp_path):
    client, _ = _client(tmp_path, vercel_analytics_token="tok")
    resp = client.get("/api/monitor/analytics", params={"token": TOKEN})
    assert resp.json() == {"configured": False, "projects": []}


def test_analytics_returns_one_tile_per_tracked_project(tmp_path, monkeypatch):
    client, conn = _client(tmp_path, vercel_analytics_token="tok")
    store.save_fact(conn, key="prj_snips", value="Snips", category=VERCEL_PROJECT_CATEGORY)
    store.save_fact(conn, key="prj_allore", value="Allore AI", category=VERCEL_PROJECT_CATEGORY)

    def fake_pageviews(token, project_id, team_id, days):
        return {"configured": True, "pageviews": 100 if project_id == "prj_snips" else 200, "days": days}

    monkeypatch.setattr(vercel_analytics, "get_pageview_summary", fake_pageviews)

    resp = client.get("/api/monitor/analytics", params={"token": TOKEN})
    body = resp.json()
    assert body["configured"] is True
    by_id = {p["project_id"]: p for p in body["projects"]}
    assert by_id["prj_snips"] == {"project_id": "prj_snips", "label": "Snips", "pageviews": 100, "days": 30}
    assert by_id["prj_allore"] == {"project_id": "prj_allore", "label": "Allore AI", "pageviews": 200, "days": 30}


def test_analytics_one_project_erroring_does_not_break_the_others(tmp_path, monkeypatch):
    client, conn = _client(tmp_path, vercel_analytics_token="tok")
    store.save_fact(conn, key="prj_good", value="Good", category=VERCEL_PROJECT_CATEGORY)
    store.save_fact(conn, key="prj_bad", value="Bad", category=VERCEL_PROJECT_CATEGORY)

    def fake_pageviews(token, project_id, team_id, days):
        if project_id == "prj_bad":
            raise vercel_analytics.VercelAnalyticsError("boom")
        return {"configured": True, "pageviews": 10, "days": days}

    monkeypatch.setattr(vercel_analytics, "get_pageview_summary", fake_pageviews)

    resp = client.get("/api/monitor/analytics", params={"token": TOKEN})
    by_id = {p["project_id"]: p for p in resp.json()["projects"]}
    assert by_id["prj_good"]["pageviews"] == 10
    assert by_id["prj_bad"]["error"] == "boom"


def test_analytics_projects_add_and_delete(tmp_path):
    client, conn = _client(tmp_path)
    add_resp = client.post("/api/monitor/analytics/projects", json={"token": TOKEN, "project_id": "prj_x", "label": "X"})
    assert add_resp.status_code == 200
    assert store.get_facts_by_category(conn, VERCEL_PROJECT_CATEGORY) == [{"key": "prj_x", "value": "X", "category": VERCEL_PROJECT_CATEGORY}]

    del_resp = client.post("/api/monitor/analytics/projects/delete", json={"token": TOKEN, "project_id": "prj_x"})
    assert del_resp.json() == {"ok": True}
    assert store.get_facts_by_category(conn, VERCEL_PROJECT_CATEGORY) == []


def test_shipping_not_configured_when_nothing_tracked(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/monitor/shipping", params={"token": TOKEN})
    assert resp.json() == {"configured": False, "repos": [], "accounts": []}


def test_shipping_repos_add_and_delete(tmp_path):
    client, conn = _client(tmp_path)
    add_resp = client.post("/api/monitor/shipping/repos", json={"token": TOKEN, "repo": "techwarq/edith", "label": "Edith"})
    assert add_resp.status_code == 200
    assert store.get_facts_by_category(conn, SHIPPING_REPO_CATEGORY) == [
        {"key": "techwarq/edith", "value": "Edith", "category": SHIPPING_REPO_CATEGORY}
    ]

    del_resp = client.post("/api/monitor/shipping/repos/delete", json={"token": TOKEN, "repo": "techwarq/edith"})
    assert del_resp.json() == {"ok": True}
    assert store.get_facts_by_category(conn, SHIPPING_REPO_CATEGORY) == []


def test_shipping_accounts_add_and_delete(tmp_path):
    client, conn = _client(tmp_path)
    add_resp = client.post("/api/monitor/shipping/accounts", json={"token": TOKEN, "username": "techwarq"})
    assert add_resp.status_code == 200
    assert store.get_facts_by_category(conn, SHIPPING_ACCOUNT_CATEGORY) == [
        {"key": "techwarq", "value": "techwarq", "category": SHIPPING_ACCOUNT_CATEGORY}
    ]

    del_resp = client.post("/api/monitor/shipping/accounts/delete", json={"token": TOKEN, "username": "techwarq"})
    assert del_resp.json() == {"ok": True}
    assert store.get_facts_by_category(conn, SHIPPING_ACCOUNT_CATEGORY) == []


def test_shipping_combines_repo_and_account_commits(tmp_path, monkeypatch):
    client, conn = _client(tmp_path)
    store.save_fact(conn, key="techwarq/edith", value="Edith", category=SHIPPING_REPO_CATEGORY)
    store.save_fact(conn, key="techwarq", value="techwarq", category=SHIPPING_ACCOUNT_CATEGORY)

    monkeypatch.setattr(
        github_shipping,
        "get_recent_commits",
        lambda repos, token: [{"repo": "techwarq/edith", "label": "Edith", "sha": "1111111", "message": "repo commit", "date": "2026-07-01T00:00:00Z"}],
    )
    monkeypatch.setattr(
        github_shipping,
        "get_account_activity",
        lambda username, token: [{"repo": "techwarq/other", "label": "other", "sha": "2222222", "message": "account commit", "date": "2026-07-02T00:00:00Z"}],
    )

    resp = client.get("/api/monitor/shipping", params={"token": TOKEN})
    body = resp.json()
    assert body["configured"] is True
    assert [c["message"] for c in body["commits"]] == ["account commit", "repo commit"]  # newest first


def test_social_summary(tmp_path):
    client, conn = _client(tmp_path)
    store.save_fact(conn, key="niche", value="AI agents", category="content_strategy")
    store.save_fact(conn, key="X voice", value="short and punchy", category=SOCIAL_SKILL_CATEGORY)

    resp = client.get("/api/monitor/social", params={"token": TOKEN})
    body = resp.json()
    assert body["content_strategy"] == [{"key": "niche", "value": "AI agents", "category": "content_strategy"}]
    assert body["skills"] == [{"title": "X voice", "preview": "short and punchy"}]


def test_ideas_bugs_crud(tmp_path):
    client, _ = _client(tmp_path)

    create_resp = client.post("/api/monitor/ideas-bugs", json={"token": TOKEN, "kind": "bug", "title": "Crashes"})
    assert create_resp.status_code == 200
    item_id = create_resp.json()["id"]

    list_resp = client.get("/api/monitor/ideas-bugs", params={"token": TOKEN})
    assert len(list_resp.json()["items"]) == 1

    resolve_resp = client.post(f"/api/monitor/ideas-bugs/{item_id}/resolve", json={"token": TOKEN})
    assert resolve_resp.json()["status"] == "resolved"

    delete_resp = client.post(f"/api/monitor/ideas-bugs/{item_id}/delete", json={"token": TOKEN})
    assert delete_resp.json() == {"ok": True}


def test_create_idea_bug_requires_kind_and_title(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/api/monitor/ideas-bugs", json={"token": TOKEN, "kind": "not-a-kind", "title": "x"})
    assert resp.status_code == 400


def test_resolve_idea_bug_not_found(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/api/monitor/ideas-bugs/999/resolve", json={"token": TOKEN})
    assert resp.status_code == 404


def test_news(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    monkeypatch.setattr(monitor_api, "fetch_news", lambda client, model, topic: f"headline about {topic or 'general'}")
    resp = client.get("/api/monitor/news", params={"token": TOKEN, "topic": "startups"})
    assert resp.json() == {"text": "headline about startups"}
