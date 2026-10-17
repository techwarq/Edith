"""Read-only Vercel tool: list projects and recent deployments.

Reuses VERCEL_ANALYTICS_TOKEN/VERCEL_TEAM_ID (already configured for the
Situation Monitor's Analytics panel — see edith/monitor/vercel_analytics.py)
rather than a second credential; the same token just needs read scope for
either use. Deliberately read-only — Sonali chose this scope over adding
write access (triggering redeploys) when asked, 2026-08-03.
"""

import logging

import requests

from edith.config import Settings
from edith.tools.base import ToolContext, tool

logger = logging.getLogger("edith.tools.vercel")

_BASE_URL = "https://api.vercel.com"
_TIMEOUT_SECONDS = 15
_NOT_CONFIGURED = "Vercel isn't configured yet (no VERCEL_ANALYTICS_TOKEN set)."


def _get(settings: Settings, path: str, params: dict):
    if settings.vercel_team_id:
        params = {**params, "teamId": settings.vercel_team_id}
    try:
        resp = requests.get(
            f"{_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {settings.vercel_analytics_token}"},
            params=params,
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        return None, f"ERROR: network error calling Vercel: {e}"
    if resp.status_code >= 400:
        return None, f"ERROR: Vercel API error ({resp.status_code}): {resp.text[:300]}"
    return resp.json(), None


@tool
def vercel_list_projects(ctx: ToolContext) -> str:
    """List the user's Vercel projects (name and id). Read-only."""
    if not ctx.settings.vercel_analytics_token:
        return _NOT_CONFIGURED
    data, err = _get(ctx.settings, "/v9/projects", {"limit": 50})
    if err:
        return err
    projects = data.get("projects", [])
    if not projects:
        return "No Vercel projects found."
    return "\n".join(f"{p['name']} ({p['id']})" for p in projects)


@tool
def vercel_list_deployments(ctx: ToolContext, project_id: str, limit: int = 5) -> str:
    """List recent deployments for a Vercel project — state (ready/building/error), URL,
    and target (production/preview). Read-only — cannot trigger a new deployment.

    Args:
        project_id: Vercel project ID or name
        limit: How many recent deployments to return (default 5)
    """
    if not ctx.settings.vercel_analytics_token:
        return _NOT_CONFIGURED
    data, err = _get(ctx.settings, "/v6/deployments", {"projectId": project_id, "limit": limit})
    if err:
        return err
    deployments = data.get("deployments", [])
    if not deployments:
        return f"No deployments found for {project_id}."
    lines = []
    for d in deployments:
        state = d.get("state") or d.get("readyState") or "unknown"
        lines.append(f"{d['uid']} — {state} — {d.get('url', 'n/a')} ({d.get('target') or 'preview'})")
    return "\n".join(lines)
