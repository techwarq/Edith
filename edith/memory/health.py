"""CRUD + summarization for health_metrics — synced from the Android app's
Health Connect integration (see edith/web/app.js's syncHealthData). One row
per (type, date); re-syncing an overlapping day upserts rather than
duplicates, since Health Connect queries are always "since last sync" and
can legitimately overlap the last-synced day.
"""

import sqlite3
from typing import Optional

VALID_TYPES = {"steps", "weight", "calories", "workouts"}


def store_metrics(conn: sqlite3.Connection, metrics: list[dict]) -> int:
    """metrics: [{"type": "steps", "date": "2026-07-19", "value": 8500, "unit": "count"}, ...].
    Returns the number of rows written. Silently skips entries with an
    unrecognized type rather than raising — the client only ever sends the
    four types it's authorized to read, but a malformed/unexpected entry
    shouldn't fail the whole sync batch."""
    written = 0
    for m in metrics:
        if m.get("type") not in VALID_TYPES:
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


def summarize(conn: sqlite3.Connection) -> str:
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
