"""track_project / untrack_project / list_projects — "what am I working on"
tracking, surfaced via the /working-on command in commands.py.

Same pattern as tracking.py's tracked URLs and monitor.py's shipping
repos/Vercel projects: reuses save_fact/forget_fact/get_facts_by_category
with a dedicated category rather than a new table. Re-calling track_project
with the same name upserts (updates the status/description), it doesn't
duplicate.
"""

import sqlite3

from edith.memory import store
from edith.tools.registry import ToolRegistry

WORKING_ON_CATEGORY = "working_on_project"


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def track_project(name: str, description: str = "") -> str:
        store.save_fact(conn, key=name, value=description or name, category=WORKING_ON_CATEGORY)
        return f"Added '{name}' to what you're working on."

    def untrack_project(name: str) -> str:
        removed = store.forget_fact(conn, name)
        return f"Removed '{name}' from what you're working on." if removed else f"'{name}' wasn't tracked."

    def list_projects() -> str:
        facts = store.get_facts_by_category(conn, WORKING_ON_CATEGORY)
        if not facts:
            return "Nothing tracked yet."
        return "\n".join(f"{f['key']}: {f['value']}" for f in facts)

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "track_project",
                "description": (
                    "Add or update a project the user is actively working on, shown via /working-on. "
                    "Call this proactively whenever they mention a project they're working on or give a "
                    "status update on one already tracked — don't wait to be asked to save it. Calling "
                    "again with the same name updates its description/status rather than duplicating."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Short stable project name, e.g. 'edith'"},
                        "description": {
                            "type": "string",
                            "description": "Brief description or current status, e.g. 'building the memory layer'",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
        track_project,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "untrack_project",
                "description": "Remove a project from the user's working-on list, e.g. once it's finished or shelved.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        untrack_project,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_projects",
                "description": "List every project currently on the user's working-on list.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        list_projects,
    )
