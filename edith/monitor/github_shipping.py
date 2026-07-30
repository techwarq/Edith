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


def get_account_activity(
    username: str, token: str, repo_limit: int = 10, per_repo_limit: int = 5
) -> list[dict[str, Any]]:
    """Auto-classified shipping log for an entire GitHub account — this is
    what lets the user just say "track my GitHub username" instead of adding
    each repo one by one; every commit is tagged with the repo it came from
    (the automatic "which app" classification), no per-repo setup needed.

    Deliberately NOT built on GET /users/{username}/events(/public): that
    endpoint is far too sparse to be a reliable activity feed in practice —
    empirically (2026-07-30), it missed real same-day pushes to a public repo
    entirely (recorded as a bare CreateEvent instead of a PushEvent) and had
    only a handful of events total for an active account, while the repos'
    own `pushed_at` timestamps showed genuinely recent work. Listing the
    account's own repos (sorted by push recency) and pulling each one's
    actual commit history via get_recent_commits is slower (repo_limit + 1
    calls instead of ~4) but reflects real activity, which is the entire
    point of a shipping log. Excludes forks — a fork's commits aren't this
    account's own shipping activity."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.get(
            f"https://api.github.com/users/{username}/repos",
            headers=headers,
            params={"sort": "pushed", "per_page": 100},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException:
        logger.warning("Network error listing GitHub repos for %s", username, exc_info=True)
        return []
    if resp.status_code >= 400:
        logger.warning("GitHub repo list failed for %s (status %s)", username, resp.status_code)
        return []

    owned_repos = [r for r in resp.json() if not r.get("fork")]
    repos = [{"repo": r["full_name"], "label": r["name"]} for r in owned_repos[:repo_limit]]
    return get_recent_commits(repos, token, per_repo_limit=per_repo_limit)
