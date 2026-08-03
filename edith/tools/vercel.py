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
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.tools.vercel")

_BASE_URL = "https://api.vercel.com"
_TIMEOUT_SECONDS = 15
_NOT_CONFIGURED = "Vercel isn't configured yet (no VERCEL_ANALYTICS_TOKEN set)."


def register(registry: ToolRegistry, settings: Settings) -> None:
    def _params(extra: dict) -> dict:
        params = dict(extra)
        if settings.vercel_team_id:
            params["teamId"] = settings.vercel_team_id
        return params

    def _get(path: str, params: dict):
        try:
            resp = requests.get(
                f"{_BASE_URL}{path}",
                headers={"Authorization": f"Bearer {settings.vercel_analytics_token}"},
                params=_params(params),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as e:
            return None, f"ERROR: network error calling Vercel: {e}"
        if resp.status_code >= 400:
            return None, f"ERROR: Vercel API error ({resp.status_code}): {resp.text[:300]}"
        return resp.json(), None

    def vercel_list_projects() -> str:
        if not settings.vercel_analytics_token:
            return _NOT_CONFIGURED
        data, err = _get("/v9/projects", {"limit": 50})
        if err:
            return err
        projects = data.get("projects", [])
        if not projects:
            return "No Vercel projects found."
        return "\n".join(f"{p['name']} ({p['id']})" for p in projects)

    def vercel_list_deployments(project_id: str, limit: int = 5) -> str:
        if not settings.vercel_analytics_token:
            return _NOT_CONFIGURED
        data, err = _get("/v6/deployments", {"projectId": project_id, "limit": limit})
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

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "vercel_list_projects",
                "description": "List the user's Vercel projects (name and id). Read-only.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        vercel_list_projects,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "vercel_list_deployments",
                "description": (
                    "List recent deployments for a Vercel project — state (ready/building/error), URL, "
                    "and target (production/preview). Read-only — cannot trigger a new deployment."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Vercel project ID or name"},
                        "limit": {"type": "integer", "description": "How many recent deployments to return (default 5)"},
                    },
                    "required": ["project_id"],
                },
            },
        },
        vercel_list_deployments,
    )
