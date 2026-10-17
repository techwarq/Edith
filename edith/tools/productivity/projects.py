"""track_project / untrack_project / list_projects — "what am I working on"
tracking, surfaced via the /working-on command in commands.py.

Same pattern as tracking.py's tracked URLs and monitor.py's shipping
repos/Vercel projects: settings rows
with a dedicated category rather than a new table. Re-calling track_project
with the same name upserts (updates the status/description), it doesn't
duplicate.
"""

from edith.memory.records import system
from edith.tools.base import ToolContext, tool

WORKING_ON_CATEGORY = "working_on_project"


@tool
def track_project(ctx: ToolContext, name: str, description: str = "") -> str:
    """Add or update a project the user is actively working on, shown via /working-on.
    Call this proactively whenever they mention a project they're working on or give a
    status update on one already tracked — don't wait to be asked to save it. Calling
    again with the same name updates its description/status rather than duplicating.

    Args:
        name: Short stable project name, e.g. 'edith'
        description: Brief description or current status, e.g. 'building the memory layer'
    """
    system.set_setting(ctx.conn, key=name, value=description or name, category=WORKING_ON_CATEGORY)
    return f"Added '{name}' to what you're working on."


@tool
def untrack_project(ctx: ToolContext, name: str) -> str:
    """Remove a project from the user's working-on list, e.g. once it's finished or shelved."""
    removed = system.delete_setting(ctx.conn, name)
    return f"Removed '{name}' from what you're working on." if removed else f"'{name}' wasn't tracked."


@tool
def list_projects(ctx: ToolContext) -> str:
    """List every project currently on the user's working-on list."""
    facts = system.list_settings(ctx.conn, WORKING_ON_CATEGORY)
    if not facts:
        return "Nothing tracked yet."
    return "\n".join(f"{f['key']}: {f['value']}" for f in facts)
