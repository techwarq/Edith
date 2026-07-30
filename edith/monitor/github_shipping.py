"""GitHub commits client for the Situation Monitor's Shipping Log panel.
Standard REST API (docs.github.com/rest/commits), no surprises: public repos
work with no token, private repos need one with repo read access.
"""

import logging
from typing import Any, Optional

import requests

logger = logging.getLogger("edith.monitor.github_shipping")

_TIMEOUT_SECONDS = 15


class GitHubError(Exception):
    pass


def get_recent_commits(repos: list[dict[str, str]], token: str, per_repo_limit: int = 8) -> list[dict[str, Any]]:
    """repos is [{"repo": "owner/name", "label": "Edith"}, ...] (label is the
    tracked repo's display name — see edith/tools/monitor.py's
    track_shipping_repo). Returns commits across all repos, newest first;
    a repo that errors (bad name, private+no token) is skipped with a logged
    warning rather than failing the whole panel."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    all_commits: list[dict[str, Any]] = []
    for entry in repos:
        repo = entry["repo"]
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{repo}/commits",
                headers=headers,
                params={"per_page": per_repo_limit},
                timeout=_TIMEOUT_SECONDS,
            )
            if resp.status_code >= 400:
                logger.warning("GitHub commits fetch failed for %s (status %s)", repo, resp.status_code)
                continue
            for c in resp.json():
                commit = c.get("commit") or {}
                all_commits.append(
                    {
                        "repo": repo,
                        "label": entry.get("label") or repo,
                        "sha": (c.get("sha") or "")[:7],
                        "message": (commit.get("message") or "").split("\n", 1)[0],
                        "author": (commit.get("author") or {}).get("name"),
                        "date": (commit.get("author") or {}).get("date"),
                        "url": c.get("html_url"),
                    }
                )
        except requests.exceptions.RequestException:
            logger.warning("Network error fetching GitHub commits for %s", repo, exc_info=True)
            continue

    all_commits.sort(key=lambda c: c.get("date") or "", reverse=True)
    return all_commits


def get_account_activity(username: str, token: str, limit: int = 20) -> list[dict[str, Any]]:
    """Auto-classified shipping log for an entire GitHub account — this is
    what lets the user just say "track my GitHub username" instead of adding
    each repo one by one; every commit is tagged with the repo it came from
    (the automatic "which app" classification), no per-repo setup needed.

    Uses GET /users/{username}/events/public (paginated) filtered to
    PushEvent, which is public activity across every repo the user pushed
    to. As of GitHub's current API, PushEvent payloads only carry
    before/head SHAs, not a commits array (that used to be included but no
    longer is) — so each push's actual commit (message/author/date) is
    fetched individually via GET /repos/{repo}/commits/{head}. A push that
    fails to resolve (deleted repo, race with a force-push, etc.) is skipped
    with a logged warning rather than failing the whole panel."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    push_events: list[dict[str, Any]] = []
    for page in range(1, 4):  # up to 300 events, matching GitHub's own cap on this endpoint
        try:
            resp = requests.get(
                f"https://api.github.com/users/{username}/events/public",
                headers=headers,
                params={"per_page": 100, "page": page},
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException:
            logger.warning("Network error fetching GitHub events for %s", username, exc_info=True)
            break
        if resp.status_code >= 400:
            logger.warning("GitHub events fetch failed for %s (status %s)", username, resp.status_code)
            break
        page_events = resp.json()
        push_events.extend(e for e in page_events if e.get("type") == "PushEvent")
        if len(page_events) < 100 or len(push_events) >= limit:
            break

    commits: list[dict[str, Any]] = []
    for event in push_events[:limit]:
        repo = (event.get("repo") or {}).get("name")
        head = (event.get("payload") or {}).get("head")
        if not repo or not head:
            continue
        try:
            resp = requests.get(f"https://api.github.com/repos/{repo}/commits/{head}", headers=headers, timeout=_TIMEOUT_SECONDS)
            if resp.status_code >= 400:
                logger.warning("GitHub commit fetch failed for %s@%s (status %s)", repo, head, resp.status_code)
                continue
            c = resp.json()
            commit = c.get("commit") or {}
            commits.append(
                {
                    "repo": repo,
                    "label": repo.split("/", 1)[-1],
                    "sha": (c.get("sha") or head)[:7],
                    "message": (commit.get("message") or "").split("\n", 1)[0],
                    "author": (commit.get("author") or {}).get("name"),
                    "date": (commit.get("author") or {}).get("date") or event.get("created_at"),
                    "url": c.get("html_url"),
                }
            )
        except requests.exceptions.RequestException:
            logger.warning("Network error fetching commit %s@%s", repo, head, exc_info=True)
            continue

    commits.sort(key=lambda c: c.get("date") or "", reverse=True)
    return commits
