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
