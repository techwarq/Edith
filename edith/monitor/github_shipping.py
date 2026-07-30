"""GitHub commits client for the Situation Monitor's Shipping Log panel.
Standard REST API (docs.github.com/rest/commits), no surprises: public repos
work with no token, private repos need one with repo read access.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger("edith.monitor.github_shipping")

_TIMEOUT_SECONDS = 15

# Conventional-commit prefixes ranked so a push's headline is the most
# noteworthy thing shipped (a feature/fix), not an incidental chore/docs
# commit that happened to be the newest in the batch. Lower rank = more
# noteworthy; anything unrecognised sits in the middle (real work, just not
# tagged), and housekeeping prefixes sink to the bottom.
_COMMIT_PRIORITY = {
    "feat": 0, "fix": 1, "perf": 2, "refactor": 3, "revert": 4,
    "build": 7, "ci": 7, "chore": 8, "docs": 8, "test": 8, "style": 8,
}
_DEFAULT_PRIORITY = 5
_PUSH_GAP_HOURS = 6.0


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


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _commit_priority(message: str) -> int:
    prefix = message.split(":", 1)[0].split("(", 1)[0].strip().lower() if ":" in message else ""
    return _COMMIT_PRIORITY.get(prefix, _DEFAULT_PRIORITY)


def group_pushes(commits: list[dict[str, Any]], gap_hours: float = _PUSH_GAP_HOURS) -> list[dict[str, Any]]:
    """Collapse a newest-first commit stream into "pushes" — the summarised
    unit the Shipping Log shows instead of every raw commit. A push is a run of
    commits to the same repo with no gap larger than `gap_hours` between them
    (GitHub's PushEvent feed is too sparse to use for this — see
    get_account_activity — so pushes are reconstructed by time-clustering the
    commits themselves). Each push is headlined by its most noteworthy commit
    (feature/fix over chore/docs, see _COMMIT_PRIORITY) with a count of the
    rest, so the panel reads as "what shipped", not a commit log."""
    open_by_repo: dict[tuple, dict[str, Any]] = {}
    pushes: list[dict[str, Any]] = []
    for c in commits:
        key = (c.get("repo"), c.get("label"))
        cur = open_by_repo.get(key)
        cdt = _parse_dt(c.get("date"))
        within = False
        if cur is not None and cdt is not None and cur["_oldest"] is not None:
            within = abs((cur["_oldest"] - cdt).total_seconds()) <= gap_hours * 3600
        if cur is not None and within:
            cur["commits"].append(c)
            cur["_oldest"] = cdt or cur["_oldest"]
        else:
            cur = {"repo": c.get("repo"), "label": c.get("label"), "commits": [c], "_oldest": cdt, "_newest": cdt}
            pushes.append(cur)
            open_by_repo[key] = cur

    result: list[dict[str, Any]] = []
    for p in pushes:
        cs = p["commits"]
        headline = min(cs, key=lambda c: (_commit_priority(c.get("message") or ""), -(len(c.get("message") or ""))))
        result.append(
            {
                "repo": p["repo"],
                "label": p["label"],
                "count": len(cs),
                "date": cs[0].get("date"),  # newest commit in the push (commits are newest-first)
                "headline": (headline.get("message") or "").strip(),
                "sha": headline.get("sha"),
                "url": headline.get("url"),
                "author": headline.get("author"),
            }
        )
    result.sort(key=lambda x: x.get("date") or "", reverse=True)
    return result
