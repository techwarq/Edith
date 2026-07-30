"""CRUD for goals / goal_milestones / insights.

Kept separate from user_profile (store.py's save_fact/etc.) since goals have
real structure — status, target dates, an ordered list of milestones — where
user_profile is flat key/value. insights is a one-way push queue: Edith adds
rows via the surface_insight tool when she has something worth the user's
attention (a goal update, an observation), the dashboard shows unseen ones,
the user dismisses them. Not a chat message — a separate "things worth
surfacing" channel the desktop/web dashboard reads.
"""

import sqlite3
from typing import Any, Optional


# ---------------------------------------------------------------------------
# goals
# ---------------------------------------------------------------------------

def create_goal(
    conn: sqlite3.Connection, title: str, description: Optional[str] = None, target_date: Optional[str] = None
) -> int:
    cur = conn.execute(
        "INSERT INTO goals (title, description, target_date) VALUES (?, ?, ?)",
        (title, description, target_date),
    )
    return cur.lastrowid


def update_goal(
    conn: sqlite3.Connection,
    goal_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    target_date: Optional[str] = None,
    status: Optional[str] = None,
) -> bool:
    fields = []
    params: list[Any] = []
    for col, val in (("title", title), ("description", description), ("target_date", target_date), ("status", status)):
        if val is not None:
            fields.append(f"{col} = ?")
            params.append(val)
    if not fields:
        return False
    fields.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')")
    params.append(goal_id)
    cur = conn.execute(f"UPDATE goals SET {', '.join(fields)} WHERE id = ?", params)
    return cur.rowcount > 0


def get_goal(conn: sqlite3.Connection, goal_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if row is None:
        return None
    goal = dict(row)
    goal["milestones"] = list_milestones(conn, goal_id)
    return goal


def list_goals(conn: sqlite3.Connection, status: Optional[str] = None) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute("SELECT * FROM goals WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM goals ORDER BY created_at DESC").fetchall()
    goals = [dict(r) for r in rows]
    for g in goals:
        g["milestones"] = list_milestones(conn, g["id"])
    return goals


def delete_goal(conn: sqlite3.Connection, goal_id: int) -> bool:
    conn.execute("DELETE FROM goal_milestones WHERE goal_id = ?", (goal_id,))
    cur = conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# milestones
# ---------------------------------------------------------------------------

def add_milestone(conn: sqlite3.Connection, goal_id: int, title: str, target_date: Optional[str] = None) -> int:
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next FROM goal_milestones WHERE goal_id = ?", (goal_id,)
    ).fetchone()["next"]
    cur = conn.execute(
        "INSERT INTO goal_milestones (goal_id, title, target_date, sort_order) VALUES (?, ?, ?, ?)",
        (goal_id, title, target_date, next_order),
    )
    return cur.lastrowid


def set_milestone_done(conn: sqlite3.Connection, milestone_id: int, done: bool) -> bool:
    cur = conn.execute(
        "UPDATE goal_milestones SET done = ?, "
        "done_at = CASE WHEN ? THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NULL END "
        "WHERE id = ?",
        (int(done), int(done), milestone_id),
    )
    return cur.rowcount > 0


def list_milestones(conn: sqlite3.Connection, goal_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM goal_milestones WHERE goal_id = ? ORDER BY sort_order ASC", (goal_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# insights ("things Edith wants to show you")
# ---------------------------------------------------------------------------

def add_insight(
    conn: sqlite3.Connection, title: str, body: Optional[str] = None, kind: str = "insight", goal_id: Optional[int] = None
) -> int:
    cur = conn.execute(
        "INSERT INTO insights (kind, title, body, goal_id) VALUES (?, ?, ?, ?)",
        (kind, title, body, goal_id),
    )
    return cur.lastrowid


def list_insights(conn: sqlite3.Connection, unseen_only: bool = True, limit: int = 50) -> list[dict[str, Any]]:
    if unseen_only:
        rows = conn.execute(
            "SELECT * FROM insights WHERE seen_at IS NULL ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM insights ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def dismiss_insight(conn: sqlite3.Connection, insight_id: int) -> bool:
    cur = conn.execute(
        "UPDATE insights SET seen_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ? AND seen_at IS NULL",
        (insight_id,),
    )
    return cur.rowcount > 0
