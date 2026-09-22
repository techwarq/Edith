import base64
from types import SimpleNamespace

from edith.tools.ops import github
from edith.tools.registry import ToolRegistry


class _FakeSettings:
    def __init__(self, token="test-token"):
        self.github_token = token


def _fake_response(json_data, status_code=200):
    return SimpleNamespace(status_code=status_code, json=lambda: json_data, text=str(json_data))


def _registry(monkeypatch, response, settings=None):
    monkeypatch.setattr(github.requests, "get", lambda *a, **k: response)
    r = ToolRegistry()
    github.register(r, settings or _FakeSettings())
    return r


def test_repo_info_formats_summary(monkeypatch):
    r = _registry(
        monkeypatch,
        _fake_response(
            {
                "full_name": "techwarq/edith",
                "description": "personal AI agent",
                "language": "Python",
                "stargazers_count": 3,
                "open_issues_count": 2,
                "default_branch": "main",
                "private": True,
            }
        ),
    )
    result = r.dispatch("github_repo_info", {"repo": "techwarq/edith"})
    assert "techwarq/edith: personal AI agent" in result
    assert "Stars: 3" in result
    assert "Private: True" in result


def test_list_issues_excludes_pull_requests(monkeypatch):
    r = _registry(
        monkeypatch,
        _fake_response(
            [
                {"number": 1, "title": "real issue", "user": {"login": "sonali"}},
                {"number": 2, "title": "a PR", "user": {"login": "sonali"}, "pull_request": {}},
            ]
        ),
    )
    result = r.dispatch("github_list_issues", {"repo": "techwarq/edith"})
    assert "#1 real issue" in result
    assert "#2" not in result


def test_list_issues_none_found(monkeypatch):
    r = _registry(monkeypatch, _fake_response([]))
    result = r.dispatch("github_list_issues", {"repo": "techwarq/edith"})
    assert result == "No open issues on techwarq/edith."


def test_list_prs_formats(monkeypatch):
    r = _registry(
        monkeypatch,
        _fake_response([{"number": 5, "title": "add feature", "user": {"login": "sonali"}, "base": {"ref": "main"}}]),
    )
    result = r.dispatch("github_list_prs", {"repo": "techwarq/edith"})
    assert result == "#5 add feature (by sonali) -> main"


def test_read_file_decodes_base64(monkeypatch):
    content = "print('hello')"
    encoded = base64.b64encode(content.encode()).decode()
    r = _registry(monkeypatch, _fake_response({"encoding": "base64", "content": encoded}))
    result = r.dispatch("github_read_file", {"repo": "techwarq/edith", "path": "main.py"})
    assert result == content


def test_read_file_directory_lists_names(monkeypatch):
    r = _registry(monkeypatch, _fake_response([{"name": "main.py"}, {"name": "README.md"}]))
    result = r.dispatch("github_read_file", {"repo": "techwarq/edith", "path": "."})
    assert result == "'.' is a directory: main.py, README.md"


def test_api_error_surfaced(monkeypatch):
    r = _registry(monkeypatch, _fake_response("not found", status_code=404))
    result = r.dispatch("github_repo_info", {"repo": "nope/nope"})
    assert result.startswith("ERROR: GitHub API error (404)")
