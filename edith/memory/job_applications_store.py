"""CRUD for the job-search/apply pipeline's job_applications + resume_profile tables.

A lead and its application attempt are 1:1 here — each discovered company either
gets drafted/sent/applied once, or is marked a skipped duplicate. Dedup is NOT a
DB uniqueness constraint on company_domain: a `failed` attempt should be retryable,
so `find_existing_application` treats sent/applied/drafted/queued_for_approval as
"already in flight" and failed/skipped_duplicate as retryable.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

_IN_FLIGHT_STATUSES = ("discovered", "drafted", "queued_for_approval", "sent", "applied")


def create_lead(
    conn: sqlite3.Connection,
    company: str,
    company_domain: Optional[str] = None,
    role_title: Optional[str] = None,
    source: Optional[str] = None,
    source_url: Optional[str] = None,
    job_posting_url: Optional[str] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO job_applications
           (company, company_domain, role_title, source, source_url, job_posting_url)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (company, company_domain, role_title, source, source_url, job_posting_url),
    )
    return cur.lastrowid


def find_existing_application(conn: sqlite3.Connection, company_domain: str) -> Optional[dict[str, Any]]:
    if not company_domain:
        return None
    placeholders = ",".join("?" for _ in _IN_FLIGHT_STATUSES)
    row = conn.execute(
        f"""SELECT * FROM job_applications
            WHERE company_domain = ? AND status IN ({placeholders})
            ORDER BY created_at DESC LIMIT 1""",
        (company_domain, *_IN_FLIGHT_STATUSES),
    ).fetchone()
    return dict(row) if row else None


def update_application(conn: sqlite3.Connection, application_id: int, **fields: Any) -> bool:
    if not fields:
        return False
    allowed = {
        "company_domain", "role_title", "channel", "contact_name", "contact_email",
        "contact_email_confidence", "status", "draft_subject", "draft_body",
        "resume_summary", "pending_action_id", "error", "sent_at", "job_posting_url",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"update_application: unknown field(s) {unknown}")

    set_clauses = [f"{k} = ?" for k in fields]
    params: list[Any] = list(fields.values())
    set_clauses.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')")
    params.append(application_id)
    cur = conn.execute(
        f"UPDATE job_applications SET {', '.join(set_clauses)} WHERE id = ?", params
    )
    return cur.rowcount > 0


def get_application(conn: sqlite3.Connection, application_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM job_applications WHERE id = ?", (application_id,)).fetchone()
    return dict(row) if row else None


def list_applications(
    conn: sqlite3.Connection, status: Optional[str] = None, limit: int = 100
) -> list[dict[str, Any]]:
    query = "SELECT * FROM job_applications"
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def count_sent_today(conn: sqlite3.Connection) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM job_applications WHERE status IN ('sent','applied') AND sent_at LIKE ?",
        (f"{today}%",),
    ).fetchone()
    return row["n"] if row else 0


def save_resume_text(conn: sqlite3.Connection, full_text: str, source_file: str) -> None:
    conn.execute(
        """INSERT INTO resume_profile (id, full_text, source_file)
           VALUES (1, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               full_text = excluded.full_text,
               source_file = excluded.source_file,
               ingested_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
        (full_text, source_file),
    )


def get_resume_text(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT full_text FROM resume_profile WHERE id = 1").fetchone()
    return row["full_text"] if row else None


def save_style_sample(conn: sqlite3.Connection, style_sample_text: str, style_sample_file: str) -> None:
    conn.execute(
        """INSERT INTO resume_profile (id, full_text, style_sample_text, style_sample_file)
           VALUES (1, '', ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               style_sample_text = excluded.style_sample_text,
               style_sample_file = excluded.style_sample_file,
               ingested_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
        (style_sample_text, style_sample_file),
    )


def get_style_sample(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT style_sample_text FROM resume_profile WHERE id = 1").fetchone()
    return row["style_sample_text"] if row else None
