"""create_todo / update_todo_status / list_todos tools — short-horizon action
items, distinct from create_goal/add_milestone (see prompts.py for the
guidance on which one to use for a given item).
"""

from edith.memory.records import planning
from edith.tools.base import ToolContext, tool


@tool
def create_todo(ctx: ToolContext, title: str, note: str = "", due_date: str = "", goal_id: int = 0) -> str:
    """Create a short-horizon todo item — a concrete near-term action with no real
    sub-structure (e.g. 'send the invoice', 'read chapter 3'). For longer-horizon
    outcomes with intermediate steps, use create_goal + add_milestone instead.

    Args:
        note: Optional extra context
        due_date: Optional date, e.g. '2026-07-22'
        goal_id: Optional id of a related goal this todo supports, omit/0 if none
    """
    todo_id = planning.create_todo(ctx.conn, title, note or None, due_date or None, goal_id or None)
    return f"Created todo #{todo_id}: {title}"


@tool
def update_todo_status(ctx: ToolContext, todo_id: int, status: str, note: str = "") -> str:
    """Mark a todo's status (todo, in_progress, or done) and optionally attach a note
    in the same call — e.g. after asking the user how something went, record their
    answer as the note while updating the status. Notes accumulate over time rather
    than overwrite, so this is safe to call repeatedly on the same todo.

    Args:
        status: One of: todo, in_progress, done
        note: Optional note to attach, e.g. the user's answer
    """
    if status not in ("todo", "in_progress", "done"):
        return "ERROR: status must be one of todo, in_progress, done."
    ok = planning.update_todo(ctx.conn, todo_id, status=status, note=note or None)
    return f"Todo #{todo_id} marked {status}." if ok else f"No todo with id {todo_id}."


@tool
def list_todos(ctx: ToolContext, status: str = "") -> str:
    """List todos, optionally filtered by status (todo, in_progress, done).

    Args:
        status: Optional: todo, in_progress, or done
    """
    todos = planning.list_todos(ctx.conn, status or None)
    if not todos:
        return "No todos found."
    lines = []
    for t in todos:
        due = f" — due {t['due_date']}" if t["due_date"] else ""
        lines.append(f"#{t['id']} [{t['status']}] {t['title']}{due}")
    return "\n".join(lines)
