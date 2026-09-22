from types import SimpleNamespace

from edith.tools.ops import vercel
from edith.tools.registry import ToolRegistry


class _FakeSettings:
    def __init__(self, token="test-token", team_id=""):
        self.vercel_analytics_token = token
        self.vercel_team_id = team_id


def _fake_response(json_data, status_code=200):
    return SimpleNamespace(status_code=status_code, json=lambda: json_data, text=str(json_data))


def _registry(monkeypatch, response, settings=None):
    monkeypatch.setattr(vercel.requests, "get", lambda *a, **k: response)
    r = ToolRegistry()
    vercel.register(r, settings or _FakeSettings())
    return r


def test_not_configured_returns_clear_message():
    r = ToolRegistry()
    vercel.register(r, _FakeSettings(token=""))
    assert r.dispatch("vercel_list_projects", {}) == vercel._NOT_CONFIGURED
    assert r.dispatch("vercel_list_deployments", {"project_id": "prj_1"}) == vercel._NOT_CONFIGURED


def test_list_projects_formats(monkeypatch):
    r = _registry(monkeypatch, _fake_response({"projects": [{"name": "edith-dashboard", "id": "prj_abc"}]}))
    result = r.dispatch("vercel_list_projects", {})
    assert result == "edith-dashboard (prj_abc)"


def test_list_projects_empty(monkeypatch):
    r = _registry(monkeypatch, _fake_response({"projects": []}))
    assert r.dispatch("vercel_list_projects", {}) == "No Vercel projects found."


def test_list_deployments_formats(monkeypatch):
    r = _registry(
        monkeypatch,
        _fake_response(
            {
                "deployments": [
                    {"uid": "dpl_1", "state": "READY", "url": "edith.vercel.app", "target": "production"}
                ]
            }
        ),
    )
    result = r.dispatch("vercel_list_deployments", {"project_id": "prj_abc"})
    assert result == "dpl_1 — READY — edith.vercel.app (production)"


def test_list_deployments_none_found(monkeypatch):
    r = _registry(monkeypatch, _fake_response({"deployments": []}))
    result = r.dispatch("vercel_list_deployments", {"project_id": "prj_abc"})
    assert result == "No deployments found for prj_abc."


def test_api_error_surfaced(monkeypatch):
    r = _registry(monkeypatch, _fake_response("forbidden", status_code=403))
    result = r.dispatch("vercel_list_projects", {})
    assert result.startswith("ERROR: Vercel API error (403)")
