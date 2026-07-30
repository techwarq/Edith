"""CRUD for todos — short-horizon action items, distinct from goals/milestones.

Unlike goal_milestones' boolean done, todos have a three-way status
(todo/in_progress/done) and a note that accumulates across updates rather
than being overwritten, so multi-day check-in answers stack up on one item
instead of clobbering each other.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


def create_todo(
    conn: sqlite3.Connection,
    title: str,
    note: Optional[str] = None,
    due_date: Optional[str] = None,
    goal_id: Optional[int] = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO todos (title, note, due_date, goal_id) VALUES (?, ?, ?, ?)",
        (title, note, due_date, goal_id),
    )
    return cur.lastrowid


def update_todo(
    conn: sqlite3.Connection,
    todo_id: int,
    status: Optional[str] = None,
    note: Optional[str] = None,
) -> bool:
    fields = []
    params: list[Any] = []

    if status is not None:
        fields.append("status = ?")
        params.append(status)

    if note:
        existing = conn.execute("SELECT note FROM todos WHERE id = ?", (todo_id,)).fetchone()
        if existing is None:
            return False
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prior = existing["note"]
        merged = f"{prior}\n[{date}] {note}" if prior else f"[{date}] {note}"
        fields.append("note = ?")
        params.append(merged)

    if not fields:
        return False
    fields.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')")
    params.append(todo_id)
    cur = conn.execute(f"UPDATE todos SET {', '.join(fields)} WHERE id = ?", params)
    return cur.rowcount > 0


def get_todo(conn: sqlite3.Connection, todo_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return dict(row) if row else None


def list_todos(
    conn: sqlite3.Connection, status: Optional[str] = None, due_date: Optional[str] = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM todos"
    clauses = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if due_date:
        clauses.append("due_date = ?")
        params.append(due_date)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY COALESCE(due_date, '9999-12-31'), created_at ASC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def delete_todo(conn: sqlite3.Connection, todo_id: int) -> bool:
    cur = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    return cur.rowcount > 0
