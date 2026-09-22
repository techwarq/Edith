"""CRUD for the Situation Monitor tab's Ideas + Bugs panel. Deliberately
simple (unlike todos_store's accumulating note) — a title, an optional note
and project tag, and an open/resolved status. Same shape whether the entry
came from the dashboard's "add" form or Edith logging one from chat
(edith/tools/ops/monitor.py).
"""

import sqlite3
from typing import Any, Optional


def create_idea_bug(
    conn: sqlite3.Connection,
    kind: str,
    title: str,
    note: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO ideas_bugs (kind, title, note, project) VALUES (?, ?, ?, ?)",
        (kind, title, note, project),
    )
    return cur.lastrowid


def get_idea_bug(conn: sqlite3.Connection, item_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM ideas_bugs WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def list_ideas_bugs(
    conn: sqlite3.Connection, kind: Optional[str] = None, status: Optional[str] = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM ideas_bugs"
    clauses = []
    params: list[Any] = []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def resolve_idea_bug(conn: sqlite3.Connection, item_id: int) -> bool:
    cur = conn.execute(
        "UPDATE ideas_bugs SET status = 'resolved', resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
        (item_id,),
    )
    return cur.rowcount > 0


def delete_idea_bug(conn: sqlite3.Connection, item_id: int) -> bool:
    cur = conn.execute("DELETE FROM ideas_bugs WHERE id = ?", (item_id,))
    return cur.rowcount > 0
