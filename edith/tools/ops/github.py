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
from edith.tools.base import ToolContext, tool

logger = logging.getLogger("edith.tools.github")

_BASE_URL = "https://api.github.com"
_TIMEOUT_SECONDS = 15
_MAX_FILE_CHARS = 8000


def _headers(settings: Settings) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


def _get(settings: Settings, path: str, params: dict | None = None):
    try:
        resp = requests.get(f"{_BASE_URL}{path}", headers=_headers(settings), params=params, timeout=_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as e:
        return None, f"ERROR: network error calling GitHub: {e}"
    if resp.status_code >= 400:
        return None, f"ERROR: GitHub API error ({resp.status_code}): {resp.text[:300]}"
    return resp.json(), None


@tool
def github_repo_info(ctx: ToolContext, repo: str) -> str:
    """Get basic info about a GitHub repo: description, language, stars, open issue count, default branch.

    Args:
        repo: 'owner/name', e.g. 'techwarq/edith'
    """
    data, err = _get(ctx.settings, f"/repos/{repo}")
    if err:
        return err
    return (
        f"{data['full_name']}: {data.get('description') or '(no description)'}\n"
        f"Language: {data.get('language') or 'n/a'} | Stars: {data['stargazers_count']} | "
        f"Open issues: {data['open_issues_count']} | Default branch: {data['default_branch']} | "
        f"Private: {data['private']}"
    )


@tool
def github_list_issues(ctx: ToolContext, repo: str, state: str = "open") -> str:
    """List issues on a GitHub repo. Read-only.

    Args:
        repo: 'owner/name'
        state: open, closed, or all (default open)
    """
    data, err = _get(ctx.settings, f"/repos/{repo}/issues", params={"state": state, "per_page": 20})
    if err:
        return err
    issues = [i for i in data if "pull_request" not in i]  # GitHub's issues endpoint includes PRs
    if not issues:
        return f"No {state} issues on {repo}."
    return "\n".join(f"#{i['number']} {i['title']} (by {i['user']['login']})" for i in issues)


@tool
def github_list_prs(ctx: ToolContext, repo: str, state: str = "open") -> str:
    """List pull requests on a GitHub repo. Read-only.

    Args:
        repo: 'owner/name'
        state: open, closed, or all (default open)
    """
    data, err = _get(ctx.settings, f"/repos/{repo}/pulls", params={"state": state, "per_page": 20})
    if err:
        return err
    if not data:
        return f"No {state} pull requests on {repo}."
    return "\n".join(f"#{p['number']} {p['title']} (by {p['user']['login']}) -> {p['base']['ref']}" for p in data)


@tool
def github_read_file(ctx: ToolContext, repo: str, path: str, ref: str = "") -> str:
    """Read a file's contents from a GitHub repo (or list a directory's contents if the path
    is a directory). Read-only — cannot write/commit.

    Args:
        repo: 'owner/name'
        path: File or directory path within the repo
        ref: Optional branch/tag/commit SHA, defaults to the default branch
    """
    data, err = _get(ctx.settings, f"/repos/{repo}/contents/{path}", params={"ref": ref} if ref else None)
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
