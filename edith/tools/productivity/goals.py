"""create_goal / update_goal_status / add_milestone / complete_milestone /
list_goals / surface_insight tools — lets Edith track what the user is
working toward and proactively flag things worth their attention.

surface_insight is deliberately NOT injected into the chat reply — it queues
a row in the insights table that the desktop/web dashboard's Insights tab
reads. This mirrors how nightly reflection's digest is "saved as a note, not
auto-sent" (see project memory): Edith can decide something is worth
flagging without it interrupting the current conversation or requiring a
send-message-style side effect.
"""

from edith.memory.records import planning
from edith.tools.base import ToolContext, tool


@tool
def create_goal(ctx: ToolContext, title: str, description: str = "", target_date: str = "") -> str:
    """Create a new tracked goal for the user — something they're working toward with a
    clear objective, not a passing preference (those are remembered automatically). Call this when
    the user states an intention with real scope ('I want to switch into ML engineering
    by end of year', 'launch the GTM campaign this quarter').

    Args:
        description: Optional extra context
        target_date: Optional target date, e.g. '2026-12-31'
    """
    goal_id = planning.create_goal(ctx.conn, title, description or None, target_date or None)
    return f"Created goal #{goal_id}: {title}"


@tool
def update_goal_status(ctx: ToolContext, goal_id: int, status: str) -> str:
    """Mark a goal as done or dropped, or reactivate it back to active.

    Args:
        status: One of: active, done, dropped
    """
    if status not in ("active", "done", "dropped"):
        return "ERROR: status must be one of active, done, dropped."
    ok = planning.update_goal(ctx.conn, goal_id, status=status)
    return f"Goal #{goal_id} marked {status}." if ok else f"No goal with id {goal_id}."


@tool
def list_goals(ctx: ToolContext, status: str = "") -> str:
    """List the user's tracked goals with milestone progress. Optionally filter by status.

    Args:
        status: Optional: active, done, or dropped
    """
    goals = planning.list_goals(ctx.conn, status or None)
    if not goals:
        return "No goals tracked yet."
    lines = []
    for g in goals:
        done = sum(1 for m in g["milestones"] if m["done"])
        total = len(g["milestones"])
        progress = f" ({done}/{total} milestones)" if total else ""
        due = f" — due {g['target_date']}" if g["target_date"] else ""
        lines.append(f"#{g['id']} [{g['status']}] {g['title']}{progress}{due}")
    return "\n".join(lines)


@tool
def add_milestone(ctx: ToolContext, goal_id: int, title: str, target_date: str = "") -> str:
    """Add a milestone (a concrete step) to an existing goal."""
    if planning.get_goal(ctx.conn, goal_id) is None:
        return f"ERROR: no goal with id {goal_id}."
    milestone_id = planning.add_milestone(ctx.conn, goal_id, title, target_date or None)
    return f"Added milestone #{milestone_id} to goal #{goal_id}: {title}"


@tool
def complete_milestone(ctx: ToolContext, milestone_id: int) -> str:
    """Mark a goal's milestone as done."""
    ok = planning.set_milestone_done(ctx.conn, milestone_id, True)
    return f"Milestone #{milestone_id} marked complete." if ok else f"No milestone with id {milestone_id}."


@tool
def surface_insight(ctx: ToolContext, title: str, body: str = "", kind: str = "insight", goal_id: int = 0) -> str:
    """Queue something worth the user's attention to show in their dashboard's Insights feed
    — NOT the current chat reply. Use this for things noticed in passing that don't need
    an immediate response: a pattern in their goal progress, an observation from tool
    results, something worth flagging next time they check in. Don't use this for things
    that belong in your normal reply to the current message.

    Args:
        kind: One of: insight, goal_update, observation (default insight)
        goal_id: Optional related goal id, omit/0 if none
    """
    if kind not in ("insight", "goal_update", "observation"):
        kind = "insight"
    insight_id = planning.add_insight(ctx.conn, title, body or None, kind, goal_id or None)
    return f"Queued insight #{insight_id} to show the user next time they open the dashboard: {title}"
