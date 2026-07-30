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

import sqlite3

from edith.memory import goals_store
from edith.tools.registry import ToolRegistry


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def create_goal(title: str, description: str = "", target_date: str = "") -> str:
        goal_id = goals_store.create_goal(conn, title, description or None, target_date or None)
        return f"Created goal #{goal_id}: {title}"

    def update_goal_status(goal_id: int, status: str) -> str:
        if status not in ("active", "done", "dropped"):
            return "ERROR: status must be one of active, done, dropped."
        ok = goals_store.update_goal(conn, goal_id, status=status)
        return f"Goal #{goal_id} marked {status}." if ok else f"No goal with id {goal_id}."

    def list_goals(status: str = "") -> str:
        goals = goals_store.list_goals(conn, status or None)
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

    def add_milestone(goal_id: int, title: str, target_date: str = "") -> str:
        if goals_store.get_goal(conn, goal_id) is None:
            return f"ERROR: no goal with id {goal_id}."
        milestone_id = goals_store.add_milestone(conn, goal_id, title, target_date or None)
        return f"Added milestone #{milestone_id} to goal #{goal_id}: {title}"

    def complete_milestone(milestone_id: int) -> str:
        ok = goals_store.set_milestone_done(conn, milestone_id, True)
        return f"Milestone #{milestone_id} marked complete." if ok else f"No milestone with id {milestone_id}."

    def surface_insight(title: str, body: str = "", kind: str = "insight", goal_id: int = 0) -> str:
        if kind not in ("insight", "goal_update", "observation"):
            kind = "insight"
        insight_id = goals_store.add_insight(conn, title, body or None, kind, goal_id or None)
        return f"Queued insight #{insight_id} to show the user next time they open the dashboard: {title}"

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "create_goal",
                "description": (
                    "Create a new tracked goal for the user — something they're working toward with a "
                    "clear objective, not a passing preference (use save_fact for those). Call this when "
                    "the user states an intention with real scope ('I want to switch into ML engineering "
                    "by end of year', 'launch the GTM campaign this quarter')."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string", "description": "Optional extra context"},
                        "target_date": {"type": "string", "description": "Optional target date, e.g. '2026-12-31'"},
                    },
                    "required": ["title"],
                },
            },
        },
        create_goal,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "update_goal_status",
                "description": "Mark a goal as done or dropped, or reactivate it back to active.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal_id": {"type": "integer"},
                        "status": {"type": "string", "description": "One of: active, done, dropped"},
                    },
                    "required": ["goal_id", "status"],
                },
            },
        },
        update_goal_status,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_goals",
                "description": "List the user's tracked goals with milestone progress. Optionally filter by status.",
                "parameters": {
                    "type": "object",
                    "properties": {"status": {"type": "string", "description": "Optional: active, done, or dropped"}},
                },
            },
        },
        list_goals,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "add_milestone",
                "description": "Add a milestone (a concrete step) to an existing goal.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "target_date": {"type": "string"},
                    },
                    "required": ["goal_id", "title"],
                },
            },
        },
        add_milestone,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "complete_milestone",
                "description": "Mark a goal's milestone as done.",
                "parameters": {
                    "type": "object",
                    "properties": {"milestone_id": {"type": "integer"}},
                    "required": ["milestone_id"],
                },
            },
        },
        complete_milestone,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "surface_insight",
                "description": (
                    "Queue something worth the user's attention to show in their dashboard's Insights feed "
                    "— NOT the current chat reply. Use this for things noticed in passing that don't need "
                    "an immediate response: a pattern in their goal progress, an observation from tool "
                    "results, something worth flagging next time they check in. Don't use this for things "
                    "that belong in your normal reply to the current message."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "kind": {"type": "string", "description": "One of: insight, goal_update, observation (default insight)"},
                        "goal_id": {"type": "integer", "description": "Optional related goal id, omit/0 if none"},
                    },
                    "required": ["title"],
                },
            },
        },
        surface_insight,
    )
