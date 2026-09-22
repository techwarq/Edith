"""create_todo / update_todo_status / list_todos tools — short-horizon action
items, distinct from create_goal/add_milestone (see prompts.py for the
guidance on which one to use for a given item).
"""

import sqlite3

from edith.memory import todos_store
from edith.tools.registry import ToolRegistry


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def create_todo(title: str, note: str = "", due_date: str = "", goal_id: int = 0) -> str:
        todo_id = todos_store.create_todo(
            conn, title, note or None, due_date or None, goal_id or None
        )
        return f"Created todo #{todo_id}: {title}"

    def update_todo_status(todo_id: int, status: str, note: str = "") -> str:
        if status not in ("todo", "in_progress", "done"):
            return "ERROR: status must be one of todo, in_progress, done."
        ok = todos_store.update_todo(conn, todo_id, status=status, note=note or None)
        return f"Todo #{todo_id} marked {status}." if ok else f"No todo with id {todo_id}."

    def list_todos(status: str = "") -> str:
        todos = todos_store.list_todos(conn, status or None)
        if not todos:
            return "No todos found."
        lines = []
        for t in todos:
            due = f" — due {t['due_date']}" if t["due_date"] else ""
            lines.append(f"#{t['id']} [{t['status']}] {t['title']}{due}")
        return "\n".join(lines)

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "create_todo",
                "description": (
                    "Create a short-horizon todo item — a concrete near-term action with no real "
                    "sub-structure (e.g. 'send the invoice', 'read chapter 3'). For longer-horizon "
                    "outcomes with intermediate steps, use create_goal + add_milestone instead."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "note": {"type": "string", "description": "Optional extra context"},
                        "due_date": {"type": "string", "description": "Optional date, e.g. '2026-07-22'"},
                        "goal_id": {
                            "type": "integer",
                            "description": "Optional id of a related goal this todo supports, omit/0 if none",
                        },
                    },
                    "required": ["title"],
                },
            },
        },
        create_todo,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "update_todo_status",
                "description": (
                    "Mark a todo's status (todo, in_progress, or done) and optionally attach a note "
                    "in the same call — e.g. after asking the user how something went, record their "
                    "answer as the note while updating the status. Notes accumulate over time rather "
                    "than overwrite, so this is safe to call repeatedly on the same todo."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todo_id": {"type": "integer"},
                        "status": {"type": "string", "description": "One of: todo, in_progress, done"},
                        "note": {"type": "string", "description": "Optional note to attach, e.g. the user's answer"},
                    },
                    "required": ["todo_id", "status"],
                },
            },
        },
        update_todo_status,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_todos",
                "description": "List todos, optionally filtered by status (todo, in_progress, done).",
                "parameters": {
                    "type": "object",
                    "properties": {"status": {"type": "string", "description": "Optional: todo, in_progress, or done"}},
                },
            },
        },
        list_todos,
    )
