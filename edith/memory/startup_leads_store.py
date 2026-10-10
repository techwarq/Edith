import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

STATUSES = ("new", "delivered", "contacted", "applied", "interview", "rejected", "skipped")
_JSON_FIELDS = ("locations", "founders", "reasons", "company_info", "sent_to")
_COLUMNS = (
    "dedup_key", "kind", "company", "domain", "fund", "source", "role_title", "job_url",
    "company_url", "locations", "region", "eligibility", "salary", "team_size", "stage",
    "description", "founders", "contact_email", "score", "reasons", "pitch", "posted_at", "company_info",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _encode(lead: dict[str, Any]) -> dict[str, Any]:
    row = {k: lead.get(k) for k in _COLUMNS}
    for k in _JSON_FIELDS:
        if row.get(k) is not None and not isinstance(row[k], str):
            row[k] = json.dumps(row[k])
    return row


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for k in _JSON_FIELDS:
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def upsert_leads(conn: sqlite3.Connection, leads: list[dict[str, Any]]) -> int:
    existing = known_keys(conn)
    inserted = 0
    for lead in leads:
        row = _encode(lead)
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        conn.execute(
            f"INSERT INTO startup_leads ({cols}) VALUES ({marks}) "
            f"ON CONFLICT(dedup_key) DO UPDATE SET score = excluded.score, reasons = excluded.reasons, "
            f"eligibility = excluded.eligibility, updated_at = '{_now()}' "
            f"WHERE startup_leads.status = 'new'",
            tuple(row.values()),
        )
        if row["dedup_key"] not in existing:
            existing.add(row["dedup_key"])
            inserted += 1
    return inserted


def prune_new(conn: sqlite3.Connection, keep: set[str]) -> int:
    stale = [k for (k,) in conn.execute(
        "SELECT dedup_key FROM startup_leads WHERE status = 'new' AND COALESCE(source, '') != 'crustdata'"
    ) if k not in keep]
    for k in stale:
        conn.execute("DELETE FROM startup_leads WHERE dedup_key = ? AND status = 'new'", (k,))
    return len(stale)


def known_keys(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT dedup_key FROM startup_leads")}


LOCATION_ALIASES = {
    "united kingdom": ("united kingdom", "uk", "england", "scotland", "wales", "london", "great britain"),
    "netherlands": ("netherlands", "holland", "amsterdam"),
    "czechia": ("czechia", "czech"),
    "united arab emirates": ("united arab emirates", "uae", "dubai", "abu dhabi"),
    "turkey": ("turkey", "türkiye", "turkiye", "istanbul"),
}


def split_locations(location: str) -> list[str]:
    return [l.strip().lower() for l in location.split(",") if l.strip()]


COUNTRY_TLDS = {"norway": ".no", "sweden": ".se", "denmark": ".dk", "finland": ".fi", "germany": ".de", "france": ".fr", "netherlands": ".nl", "spain": ".es", "italy": ".it", "poland": ".pl", "portugal": ".pt", "austria": ".at", "switzerland": ".ch", "belgium": ".be", "ireland": ".ie", "estonia": ".ee", "lithuania": ".lt", "latvia": ".lv", "czechia": ".cz", "united kingdom": ".uk", "iceland": ".is", "united arab emirates": ".ae", "saudi arabia": ".sa", "israel": ".il"}


def pick_new(
    conn: sqlite3.Connection,
    limit: int,
    kind: Optional[str] = None,
    min_score: float = 0,
    location: Optional[str] = None,
    max_team: Optional[int] = None,
    min_team: Optional[int] = None,
    allow_unknown_team: bool = False,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM startup_leads WHERE status = 'new' AND score >= ?"
    params: list[Any] = [min_score]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if location:
        clauses = []
        for loc in split_locations(location):
            for term in LOCATION_ALIASES.get(loc, (loc,)):
                clauses.append("lower(locations) LIKE ? OR lower(fund) LIKE ?")
                params += [f"%{term}%", f"%{term}%"]
            if loc in COUNTRY_TLDS:
                clauses.append("domain LIKE ?")
                params.append(f"%{COUNTRY_TLDS[loc]}")
        if clauses:
            sql += " AND (" + " OR ".join(clauses) + ")"
    if min_team or max_team:
        sql += " AND (team_size BETWEEN ? AND ?" + (" OR team_size IS NULL)" if allow_unknown_team else ")")
        params += [min_team or 0, max_team or 10**9]
    sql += " ORDER BY score DESC, found_at DESC LIMIT ?"
    params.append(limit)
    return [_decode(r) for r in conn.execute(sql, params)]


def count_new(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM startup_leads WHERE status = 'new'").fetchone()[0]


def contacted_domains(conn: sqlite3.Connection) -> set[str]:
    domains: set[str] = set()
    for sql in (
        "SELECT domain FROM startup_leads WHERE status NOT IN ('new','skipped') AND domain IS NOT NULL",
        "SELECT company_domain FROM job_applications WHERE company_domain IS NOT NULL",
        "SELECT company_domain FROM outreach_prospects WHERE company_domain IS NOT NULL",
    ):
        domains.update(r[0] for r in conn.execute(sql) if r[0])
    return domains


def used_company_names(conn: sqlite3.Connection) -> set[str]:
    names: set[str] = set()
    for sql in (
        "SELECT company FROM startup_leads WHERE status NOT IN ('new','skipped')",
        "SELECT company FROM job_applications WHERE company IS NOT NULL",
        "SELECT company FROM outreach_prospects WHERE company IS NOT NULL",
    ):
        names.update(r[0] for r in conn.execute(sql) if r[0])
    return names


def mark_delivered(conn: sqlite3.Connection, lead_id: int, **fields: Any) -> None:
    sets = {"status": "delivered", "delivered_at": _now(), "updated_at": _now()}
    for k in ("founders", "contact_email", "pitch", "reasons", "company_info", "team_size", "stage", "draft_to", "draft_subject", "draft_body"):
        if k in fields and fields[k] is not None:
            v = fields[k]
            sets[k] = json.dumps(v) if k in _JSON_FIELDS and not isinstance(v, str) else v
    clause = ", ".join(f"{k} = ?" for k in sets)
    conn.execute(f"UPDATE startup_leads SET {clause} WHERE id = ?", (*sets.values(), lead_id))


def set_company_info(conn: sqlite3.Connection, lead_id: int, info: dict[str, Any], team_size: Optional[int], stage: Optional[str]) -> None:
    conn.execute(
        "UPDATE startup_leads SET company_info = ?, team_size = COALESCE(?, team_size), stage = COALESCE(?, stage), updated_at = ? WHERE id = ?",
        (json.dumps(info), team_size, stage, _now(), lead_id),
    )


def set_contacts(conn: sqlite3.Connection, lead_id: int, founders: Optional[list[dict[str, Any]]], contact_email: Optional[str]) -> None:
    conn.execute(
        "UPDATE startup_leads SET founders = ?, contact_email = COALESCE(?, contact_email), updated_at = ? WHERE id = ?",
        (json.dumps(founders or []), contact_email, _now(), lead_id),
    )


def save_draft(conn: sqlite3.Connection, lead_id: int, to: Optional[str], subject: str, body: str) -> None:
    conn.execute(
        "UPDATE startup_leads SET draft_to = ?, draft_subject = ?, draft_body = ?, updated_at = ? WHERE id = ?",
        (to, subject, body, _now(), lead_id),
    )


def sent_recipients(lead: dict[str, Any]) -> list[str]:
    if lead.get("sent_to"):
        return [e.lower() for e in lead["sent_to"]]
    if lead.get("sent_at") and lead.get("draft_to"):
        return [e.strip().lower() for e in lead["draft_to"].split(",") if e.strip()]
    return []


def mark_sent(conn: sqlite3.Connection, lead_id: int, recipients: list[str], subject: str, body: str) -> None:
    lead = get_lead(conn, lead_id) or {}
    sent = list(dict.fromkeys(sent_recipients(lead) + [r.lower() for r in recipients]))
    conn.execute(
        "UPDATE startup_leads SET status = 'contacted', draft_subject = ?, draft_body = ?, sent_to = ?, sent_at = ?, updated_at = ? WHERE id = ?",
        (subject, body, json.dumps(sent), _now(), _now(), lead_id),
    )


def set_region(conn: sqlite3.Connection, lead_id: int, region: str) -> None:
    conn.execute("UPDATE startup_leads SET region = ?, updated_at = ? WHERE id = ?", (region, _now(), lead_id))


def update_status(conn: sqlite3.Connection, lead_id: int, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    cur = conn.execute(
        "UPDATE startup_leads SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), lead_id)
    )
    return cur.rowcount > 0


def get_lead(conn: sqlite3.Connection, lead_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM startup_leads WHERE id = ?", (lead_id,)).fetchone()
    return _decode(row) if row else None


def list_leads(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    region: Optional[str] = None,
    min_score: float = 0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM startup_leads WHERE score >= ?"
    params: list[Any] = [min_score]
    for col, val in (("status", status), ("kind", kind), ("region", region)):
        if val:
            sql += f" AND {col} = ?"
            params.append(val)
    sql += " ORDER BY COALESCE(delivered_at, found_at) DESC, score DESC LIMIT ?"
    params.append(limit)
    return [_decode(r) for r in conn.execute(sql, params)]


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for status, n in conn.execute("SELECT status, COUNT(*) FROM startup_leads GROUP BY status"):
        out[status] = n
    return out
