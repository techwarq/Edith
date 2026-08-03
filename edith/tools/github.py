"""Read-only GitHub tool: repo info, issues, PRs, file contents.

Reuses GITHUB_TOKEN (already configured for the Situation Monitor's Shipping
Log panel — see edith/monitor/github_shipping.py) rather than a second
credential; public repos work with no token, private repos need one with
repo read access. Deliberately read-only — Sonali chose this scope over
adding write access (creating issues/comments) when asked, 2026-08-03.
"""

import base64
import logging

import requests

from edith.config import Settings
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.tools.github")

_BASE_URL = "https://api.github.com"
_TIMEOUT_SECONDS = 15
_MAX_FILE_CHARS = 8000


def register(registry: ToolRegistry, settings: Settings) -> None:
    def _headers() -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        return headers

    def _get(path: str, params: dict | None = None):
        try:
            resp = requests.get(f"{_BASE_URL}{path}", headers=_headers(), params=params, timeout=_TIMEOUT_SECONDS)
        except requests.exceptions.RequestException as e:
            return None, f"ERROR: network error calling GitHub: {e}"
        if resp.status_code >= 400:
            return None, f"ERROR: GitHub API error ({resp.status_code}): {resp.text[:300]}"
        return resp.json(), None

    def github_repo_info(repo: str) -> str:
        data, err = _get(f"/repos/{repo}")
        if err:
            return err
        return (
            f"{data['full_name']}: {data.get('description') or '(no description)'}\n"
            f"Language: {data.get('language') or 'n/a'} | Stars: {data['stargazers_count']} | "
            f"Open issues: {data['open_issues_count']} | Default branch: {data['default_branch']} | "
            f"Private: {data['private']}"
        )

    def github_list_issues(repo: str, state: str = "open") -> str:
        data, err = _get(f"/repos/{repo}/issues", params={"state": state, "per_page": 20})
        if err:
            return err
        issues = [i for i in data if "pull_request" not in i]  # GitHub's issues endpoint includes PRs
        if not issues:
            return f"No {state} issues on {repo}."
        return "\n".join(f"#{i['number']} {i['title']} (by {i['user']['login']})" for i in issues)

    def github_list_prs(repo: str, state: str = "open") -> str:
        data, err = _get(f"/repos/{repo}/pulls", params={"state": state, "per_page": 20})
        if err:
            return err
        if not data:
            return f"No {state} pull requests on {repo}."
        return "\n".join(f"#{p['number']} {p['title']} (by {p['user']['login']}) -> {p['base']['ref']}" for p in data)

    def github_read_file(repo: str, path: str, ref: str = "") -> str:
        data, err = _get(f"/repos/{repo}/contents/{path}", params={"ref": ref} if ref else None)
        if err:
            return err
        if isinstance(data, list):
            return f"'{path}' is a directory: " + ", ".join(item["name"] for item in data)
        if data.get("encoding") != "base64":
            return f"ERROR: unexpected encoding '{data.get('encoding')}' for {path}"
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        if len(content) > _MAX_FILE_CHARS:
            return content[:_MAX_FILE_CHARS] + "\n...(truncated)"
        return content

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "github_repo_info",
                "description": "Get basic info about a GitHub repo: description, language, stars, open issue count, default branch.",
                "parameters": {
                    "type": "object",
                    "properties": {"repo": {"type": "string", "description": "'owner/name', e.g. 'techwarq/edith'"}},
                    "required": ["repo"],
                },
            },
        },
        github_repo_info,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "github_list_issues",
                "description": "List issues on a GitHub repo. Read-only.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "'owner/name'"},
                        "state": {"type": "string", "description": "open, closed, or all (default open)"},
                    },
                    "required": ["repo"],
                },
            },
        },
        github_list_issues,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "github_list_prs",
                "description": "List pull requests on a GitHub repo. Read-only.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "'owner/name'"},
                        "state": {"type": "string", "description": "open, closed, or all (default open)"},
                    },
                    "required": ["repo"],
                },
            },
        },
        github_list_prs,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "github_read_file",
                "description": (
                    "Read a file's contents from a GitHub repo (or list a directory's contents if the path "
                    "is a directory). Read-only — cannot write/commit."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "'owner/name'"},
                        "path": {"type": "string", "description": "File or directory path within the repo"},
                        "ref": {"type": "string", "description": "Optional branch/tag/commit SHA, defaults to the default branch"},
                    },
                    "required": ["repo", "path"],
                },
            },
        },
        github_read_file,
    )
