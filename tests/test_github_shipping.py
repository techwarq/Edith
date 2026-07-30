from edith.monitor import github_shipping


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_get_recent_commits_formats_and_sorts(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        if "techwarq/edith" in url:
            return _FakeResponse(
                200,
                [
                    {
                        "sha": "abc1234567",
                        "html_url": "https://github.com/techwarq/edith/commit/abc1234567",
                        "commit": {"message": "fix infinite redirect\n\nmore detail", "author": {"name": "Sonali", "date": "2026-07-20T10:00:00Z"}},
                    }
                ],
            )
        return _FakeResponse(
            200,
            [
                {
                    "sha": "def7654321",
                    "html_url": "https://github.com/techwarq/other/commit/def7654321",
                    "commit": {"message": "add notifications", "author": {"name": "Sonali", "date": "2026-07-25T10:00:00Z"}},
                }
            ],
        )

    monkeypatch.setattr(github_shipping.requests, "get", fake_get)

    repos = [{"repo": "techwarq/edith", "label": "Edith"}, {"repo": "techwarq/other", "label": "Other"}]
    commits = github_shipping.get_recent_commits(repos, token="")

    assert len(commits) == 2
    assert commits[0]["repo"] == "techwarq/other"  # newer date sorts first
    assert commits[0]["message"] == "add notifications"
    assert commits[1]["sha"] == "abc1234"  # truncated to 7 chars
    assert commits[1]["message"] == "fix infinite redirect"  # only first line kept


def test_get_recent_commits_skips_repo_on_error(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(404, {"message": "Not Found"})

    monkeypatch.setattr(github_shipping.requests, "get", fake_get)
    commits = github_shipping.get_recent_commits([{"repo": "nope/nope", "label": "Nope"}], token="")
    assert commits == []


def test_get_recent_commits_includes_auth_header_when_token_given(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["headers"] = headers
        return _FakeResponse(200, [])

    monkeypatch.setattr(github_shipping.requests, "get", fake_get)
    github_shipping.get_recent_commits([{"repo": "a/b", "label": "AB"}], token="secret-token")
    assert captured["headers"]["Authorization"] == "Bearer secret-token"


def _push_event(repo, head, created_at):
    return {"type": "PushEvent", "repo": {"name": repo}, "payload": {"head": head}, "created_at": created_at}


def test_get_account_activity_fetches_head_commit_per_push(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/events/public"):
            if params["page"] == 1:
                return _FakeResponse(
                    200,
                    [
                        _push_event("techwarq/edith", "abc1234567", "2026-07-30T01:00:00Z"),
                        _push_event("techwarq/allore-be", "def7654321", "2026-07-01T19:17:24Z"),
                        {"type": "CreateEvent", "repo": {"name": "techwarq/edith"}, "payload": {}, "created_at": "2026-07-29T00:00:00Z"},
                    ],
                )
            return _FakeResponse(200, [])
        if "abc1234567" in url:
            return _FakeResponse(
                200,
                {
                    "sha": "abc1234567",
                    "html_url": "https://github.com/techwarq/edith/commit/abc1234567",
                    "commit": {"message": "add monitor tab", "author": {"name": "techwarq", "date": "2026-07-30T01:00:05Z"}},
                },
            )
        if "def7654321" in url:
            return _FakeResponse(
                200,
                {
                    "sha": "def7654321",
                    "html_url": "https://github.com/techwarq/allore-be/commit/def7654321",
                    "commit": {"message": "chore: gitignore", "author": {"name": "techwarq", "date": "2026-07-01T19:17:23Z"}},
                },
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(github_shipping.requests, "get", fake_get)
    commits = github_shipping.get_account_activity("techwarq", token="")

    assert len(commits) == 2
    assert commits[0]["repo"] == "techwarq/edith"
    assert commits[0]["label"] == "edith"
    assert commits[0]["message"] == "add monitor tab"
    assert commits[1]["label"] == "allore-be"


def test_get_account_activity_skips_push_when_commit_fetch_fails(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/events/public"):
            if params["page"] == 1:
                return _FakeResponse(200, [_push_event("techwarq/nope", "deadbeef", "2026-07-30T01:00:00Z")])
            return _FakeResponse(200, [])
        return _FakeResponse(404, {"message": "Not Found"})

    monkeypatch.setattr(github_shipping.requests, "get", fake_get)
    commits = github_shipping.get_account_activity("techwarq", token="")
    assert commits == []


def test_get_account_activity_stops_paginating_on_short_page(monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/events/public"):
            calls.append(params["page"])
            return _FakeResponse(200, [_push_event("a/b", "sha1", "2026-07-01T00:00:00Z")])  # < 100, stops after page 1
        return _FakeResponse(200, {"sha": "sha1", "html_url": "u", "commit": {"message": "m", "author": {"name": "x", "date": "d"}}})

    monkeypatch.setattr(github_shipping.requests, "get", fake_get)
    github_shipping.get_account_activity("techwarq", token="")
    assert calls == [1]
