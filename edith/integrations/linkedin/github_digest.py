"""GitHub shipped digest — what did techwarq ship this week?

Uses public GitHub API (no token needed for public repos; GITHUB_TOKEN from
settings adds private repos + higher rate limit). Powers the daily viral queue:
educational posts teach the technique behind the commit, app posts show outcome.
"""
import logging
import os
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger("edith.integrations.linkedin.github_digest")

BASE = "https://api.github.com"
TIMEOUT = 15

# techwarq's app repos (most active first). Override via GITHUB_DIGEST_REPOS="owner/a,owner/b".
DEFAULT_REPOS = [
    "techwarq/abstraklabs",
    "techwarq/agent-api",
    "techwarq/allore-be",
    "techwarq/linkedin_scraper",
    "techwarq/tax-doc-checklist",
    "techwarq/Edith",
    "techwarq/ai-lens",
    "techwarq/ai_order_supervisor",
    "techwarq/lang-up",
]

def _repos() -> list[str]:
    raw = os.environ.get("GITHUB_DIGEST_REPOS", "").strip()
    if raw:
        return [r.strip() for r in raw.split(",") if r.strip()]
    return DEFAULT_REPOS

def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "edith-linkedin-growth"}
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h

def _get(path: str, params: dict | None = None):
    try:
        r = requests.get(f"{BASE}{path}", headers=_headers(), params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        logger.warning("github digest network error: %s", e)
        return None
    if r.status_code == 403 and "rate limit" in r.text.lower():
        logger.warning("github rate limited (no token?) — set GITHUB_TOKEN for 5000/hr")
        return None
    if r.status_code >= 400:
        logger.warning("github %s -> %s %s", path, r.status_code, r.text[:200])
        return None
    try:
        return r.json()
    except Exception:
        return None

def get_recent_commits(repo: str, since_days: int = 7, per_repo: int = 8) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    data = _get(f"/repos/{repo}/commits", params={"since": since, "per_page": per_repo})
    if not data:
        return []
    out = []
    for c in data:
        try:
            out.append({
                "repo": repo,
                "sha": (c.get("sha") or "")[:7],
                "date": (c.get("commit", {}).get("author", {}).get("date") or "")[:10],
                "message": (c.get("commit", {}).get("message") or "").split("\n")[0][:160],
                "url": c.get("html_url", ""),
            })
        except Exception:
            continue
    return out

def get_repo_info(repo: str) -> dict:
    data = _get(f"/repos/{repo}")
    if not data:
        return {"repo": repo}
    return {
        "repo": repo,
        "description": data.get("description") or "",
        "language": data.get("language") or "",
        "stars": data.get("stargazers_count", 0),
        "pushed_at": (data.get("pushed_at") or "")[:10],
    }

def build_digest(since_days: int = 7, per_repo: int = 8) -> dict:
    """Returns {repos: [...], commits: [...], summary: str} for prompt injection."""
    repos = _repos()
    all_commits: list[dict] = []
    infos: list[dict] = []
    for repo in repos:
        commits = get_recent_commits(repo, since_days=since_days, per_repo=per_repo)
        info = get_repo_info(repo)
        info["commit_count"] = len(commits)
        infos.append(info)
        all_commits.extend(commits)
    all_commits.sort(key=lambda c: c.get("date", ""), reverse=True)

    if not all_commits:
        summary = "(no commits in window — check GITHUB_TOKEN / repo list; fall back to recent skills + goals)"
    else:
        lines = [f"- {c['date']} {c['repo']}: {c['message']}" for c in all_commits[:20]]
        summary = f"{len(all_commits)} commits across {len([i for i in infos if i.get('commit_count')])} active repos in last {since_days}d:\n" + "\n".join(lines)
    return {"repos": infos, "commits": all_commits, "summary": summary, "since_days": since_days}
