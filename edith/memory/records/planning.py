"""Structured planning records: goals + milestones, insights, todos, ideas/bugs, and
synced health metrics. These back dashboard tabs and tools; the brain links notes to
them through memory_refs rather than duplicating them."""

import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# goals, milestones, insights
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# todos
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ideas / bugs
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# health metrics
# ---------------------------------------------------------------------------

HEALTH_TYPES = {"steps", "weight", "calories", "workouts"}


def store_metrics(conn: sqlite3.Connection, metrics: list[dict]) -> int:
    """metrics: [{"type": "steps", "date": "2026-07-19", "value": 8500, "unit": "count"}, ...].
    Returns the number of rows written. Silently skips entries with an
    unrecognized type rather than raising — the client only ever sends the
    four types it's authorized to read, but a malformed/unexpected entry
    shouldn't fail the whole sync batch."""
    written = 0
    for m in metrics:
        if m.get("type") not in HEALTH_TYPES:
            continue
        conn.execute(
            "INSERT INTO health_metrics (type, date, value, unit) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(type, date) DO UPDATE SET value = excluded.value, unit = excluded.unit",
            (m["type"], m["date"], m["value"], m.get("unit")),
        )
        written += 1
    return written


def get_recent_metrics(conn: sqlite3.Connection, type_: str, days: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT type, date, value, unit FROM health_metrics "
        "WHERE type = ? AND date >= date('now', ?) ORDER BY date ASC",
        (type_, f"-{days} days"),
    ).fetchall()
    return [dict(r) for r in rows]


def latest_metric(conn: sqlite3.Connection, type_: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT type, date, value, unit FROM health_metrics WHERE type = ? ORDER BY date DESC LIMIT 1",
        (type_,),
    ).fetchone()
    return dict(row) if row else None


def summarize_health(conn: sqlite3.Connection) -> str:
    """Human-readable snapshot for get_health_summary — latest weight, 7-day
    average steps, recent workout count. Returns a "nothing synced yet"
    message rather than an empty string if health_metrics has no rows,
    since the caller (the LLM) should say that plainly rather than guess."""
    lines = []

    weight = latest_metric(conn, "weight")
    if weight:
        lines.append(f"Latest weight: {weight['value']} {weight['unit'] or 'kg'} (as of {weight['date']})")

    steps = get_recent_metrics(conn, "steps", days=7)
    if steps:
        avg = sum(s["value"] for s in steps) / len(steps)
        lines.append(f"Average steps over the last {len(steps)} synced day(s): {avg:.0f}")

    calories = get_recent_metrics(conn, "calories", days=7)
    if calories:
        avg = sum(c["value"] for c in calories) / len(calories)
        lines.append(f"Average active calories burned over the last {len(calories)} synced day(s): {avg:.0f}")

    workouts = get_recent_metrics(conn, "workouts", days=7)
    if workouts:
        lines.append(f"Workouts logged in the last 7 days: {len(workouts)}")

    if not lines:
        return "No health data has been synced yet — run /health login in the Android app to connect Health Connect."
    return "\n".join(lines)
