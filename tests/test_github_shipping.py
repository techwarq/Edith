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
