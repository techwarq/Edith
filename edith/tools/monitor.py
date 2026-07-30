"""Situation Monitor tab tools: log_idea/log_bug/list/resolve for the Ideas +
Bugs panel, and track/untrack/list for which GitHub repos back the Shipping
Log panel. Tracked repos reuse save_fact/get_facts_by_category the same way
tracking.py reuses them for tracked URLs — the key is "owner/name", the
value is a display label, category is fixed to SHIPPING_REPO_CATEGORY.
"""

import sqlite3

from edith.memory import ideas_bugs_store, store
from edith.tools.registry import ToolRegistry

SHIPPING_REPO_CATEGORY = "shipping_repo"
VERCEL_PROJECT_CATEGORY = "vercel_project"


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def _log(kind: str, title: str, project: str, note: str) -> str:
        item_id = ideas_bugs_store.create_idea_bug(conn, kind, title, note or None, project or None)
        return f"Logged {kind} #{item_id}: {title}"

    def log_idea(title: str, project: str = "", note: str = "") -> str:
        return _log("idea", title, project, note)

    def log_bug(title: str, project: str = "", note: str = "") -> str:
        return _log("bug", title, project, note)

    def list_ideas_bugs(kind: str = "", status: str = "open") -> str:
        items = ideas_bugs_store.list_ideas_bugs(conn, kind or None, status or None)
        if not items:
            return "Nothing logged yet."
        lines = []
        for i in items:
            tag = f"[{i['project']}] " if i["project"] else ""
            lines.append(f"#{i['id']} ({i['kind']}) {tag}{i['title']}")
        return "\n".join(lines)

    def resolve_idea_bug(item_id: int) -> str:
        ok = ideas_bugs_store.resolve_idea_bug(conn, item_id)
        return f"Marked #{item_id} resolved." if ok else f"No idea/bug with id {item_id}."

    def track_shipping_repo(repo: str, label: str = "") -> str:
        store.save_fact(conn, key=repo, value=label or repo, category=SHIPPING_REPO_CATEGORY)
        return f"Now tracking {repo} in the shipping log."

    def untrack_shipping_repo(repo: str) -> str:
        removed = store.forget_fact(conn, repo)
        return f"Stopped tracking {repo}." if removed else f"{repo} wasn't being tracked."

    def list_shipping_repos() -> str:
        facts = store.get_facts_by_category(conn, SHIPPING_REPO_CATEGORY)
        if not facts:
            return "No repos are being tracked in the shipping log yet."
        return "\n".join(f"{f['key']} ({f['value']})" for f in facts)

    def track_vercel_project(project_id: str, label: str = "") -> str:
        store.save_fact(conn, key=project_id, value=label or project_id, category=VERCEL_PROJECT_CATEGORY)
        return f"Now tracking {label or project_id} ({project_id}) in the Analytics panel."

    def untrack_vercel_project(project_id: str) -> str:
        removed = store.forget_fact(conn, project_id)
        return f"Stopped tracking {project_id}." if removed else f"{project_id} wasn't being tracked."

    def list_vercel_projects() -> str:
        facts = store.get_facts_by_category(conn, VERCEL_PROJECT_CATEGORY)
        if not facts:
            return "No Vercel projects are being tracked in the Analytics panel yet."
        return "\n".join(f"{f['value']} ({f['key']})" for f in facts)

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "log_idea",
                "description": (
                    "Log a product/feature idea to the Situation Monitor dashboard's Ideas + Bugs panel. "
                    "Call this when the user mentions an idea they want to remember or come back to later."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "project": {"type": "string", "description": "Optional project/product this belongs to"},
                        "note": {"type": "string", "description": "Optional extra detail"},
                    },
                    "required": ["title"],
                },
            },
        },
        log_idea,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "log_bug",
                "description": (
                    "Log a bug to the Situation Monitor dashboard's Ideas + Bugs panel. Call this when the "
                    "user reports something broken and wants it tracked."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "project": {"type": "string", "description": "Optional project/product this belongs to"},
                        "note": {"type": "string", "description": "Optional extra detail"},
                    },
                    "required": ["title"],
                },
            },
        },
        log_bug,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_ideas_bugs",
                "description": "List logged ideas/bugs from the Situation Monitor dashboard. Defaults to open items only.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "description": "Optional: idea or bug"},
                        "status": {"type": "string", "description": "Optional: open or resolved (default open)"},
                    },
                },
            },
        },
        list_ideas_bugs,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "resolve_idea_bug",
                "description": "Mark a logged idea or bug as resolved, given its id.",
                "parameters": {
                    "type": "object",
                    "properties": {"item_id": {"type": "integer"}},
                    "required": ["item_id"],
                },
            },
        },
        resolve_idea_bug,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "track_shipping_repo",
                "description": (
                    "Add a GitHub repo to the Situation Monitor dashboard's Shipping Log panel, which shows "
                    "its recent commits. Call when the user names a repo/project they want to see ship activity for."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "'owner/name', e.g. 'techwarq/edith'"},
                        "label": {"type": "string", "description": "Optional display name, defaults to the repo path"},
                    },
                    "required": ["repo"],
                },
            },
        },
        track_shipping_repo,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "untrack_shipping_repo",
                "description": "Stop showing a repo's commits in the Shipping Log panel.",
                "parameters": {
                    "type": "object",
                    "properties": {"repo": {"type": "string"}},
                    "required": ["repo"],
                },
            },
        },
        untrack_shipping_repo,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_shipping_repos",
                "description": "List every repo currently tracked in the Shipping Log panel.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        list_shipping_repos,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "track_vercel_project",
                "description": (
                    "Add a Vercel project to the Situation Monitor dashboard's Analytics panel, which shows "
                    "its pageviews. Call when the user names an app/project they want visitor stats tracked for."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Vercel project ID, e.g. 'prj_abc123'"},
                        "label": {"type": "string", "description": "Optional display name, defaults to the project id"},
                    },
                    "required": ["project_id"],
                },
            },
        },
        track_vercel_project,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "untrack_vercel_project",
                "description": "Stop showing a Vercel project's pageviews in the Analytics panel.",
                "parameters": {
                    "type": "object",
                    "properties": {"project_id": {"type": "string"}},
                    "required": ["project_id"],
                },
            },
        },
        untrack_vercel_project,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_vercel_projects",
                "description": "List every Vercel project currently tracked in the Analytics panel.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        list_vercel_projects,
    )
