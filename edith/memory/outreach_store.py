"""CRUD for LinkedIn/founder outreach prospects (semi-auto).

Separate from job_applications: a job lead is a company/role to apply to,
a prospect is a *person* (founder/hiring manager) to cold-email or LinkedIn-DM.
Semi-auto by design — Edith drafts, user sends from their own LinkedIn.
"""

import sqlite3
from typing import Any, Optional


def create_prospect(
    conn: sqlite3.Connection,
    name: str,
    linkedin_url: str | None = None,
    company: str | None = None,
    company_domain: str | None = None,
    role: str | None = None,
    contact_email: str | None = None,
    context: str | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO outreach_prospects
           (name, linkedin_url, company, company_domain, role, contact_email, context)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (name, linkedin_url, company, company_domain, role, contact_email, context),
    )
    return cur.lastrowid


def find_existing_prospect(
    conn: sqlite3.Connection, linkedin_url: str = "", contact_email: str = "", company_domain: str = ""
) -> Optional[dict[str, Any]]:
    if linkedin_url:
        row = conn.execute(
            "SELECT * FROM outreach_prospects WHERE linkedin_url = ? ORDER BY created_at DESC LIMIT 1",
            (linkedin_url,),
        ).fetchone()
        if row:
            return dict(row)
    if contact_email:
        row = conn.execute(
            "SELECT * FROM outreach_prospects WHERE contact_email = ? ORDER BY created_at DESC LIMIT 1",
            (contact_email,),
        ).fetchone()
        if row:
            return dict(row)
    if company_domain:
        row = conn.execute(
            """SELECT * FROM outreach_prospects WHERE company_domain = ?
               AND status IN ('queued','contacted') ORDER BY created_at DESC LIMIT 1""",
            (company_domain,),
        ).fetchone()
        if row:
            return dict(row)
    return None


def get_prospect(conn: sqlite3.Connection, prospect_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM outreach_prospects WHERE id = ?", (prospect_id,)).fetchone()
    return dict(row) if row else None


def list_prospects(
    conn: sqlite3.Connection, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            "SELECT * FROM outreach_prospects WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM outreach_prospects ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_prospect(conn: sqlite3.Connection, prospect_id: int, **fields: Any) -> bool:
    if not fields:
        return False
    allowed = {
        "linkedin_url", "company", "company_domain", "role", "contact_email",
        "context", "dm_draft", "email_draft_subject", "email_draft_body", "status",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"update_prospect: unknown field(s) {unknown}")
    set_clauses = [f"{k} = ?" for k in fields]
    params: list[Any] = list(fields.values())
    set_clauses.append("updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')")
    params.append(prospect_id)
    cur = conn.execute(
        f"UPDATE outreach_prospects SET {', '.join(set_clauses)} WHERE id = ?", params
    )
    return cur.rowcount > 0
