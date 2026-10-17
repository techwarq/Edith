"""SQLite persistence for LinkedIn Growth Engine.

Two personas: personal (manual) vs company (autopost). Stats loop feeds back.
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

LINKEDIN_SCHEMA = """
-- Authors: personal (urn:li:person:...) vs company (urn:li:organization:...)
CREATE TABLE IF NOT EXISTS linkedin_authors (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL CHECK(type IN ('personal','company')),
    urn             TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    vanity_name     TEXT,
    access_token    TEXT,
    refresh_token   TEXT,
    expires_at      TEXT,
    scopes          TEXT,
    onboarding_done INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Goals scoped per author (extends edith goals concept but linkedin-specific)
CREATE TABLE IF NOT EXISTS linkedin_goals (
    id              TEXT PRIMARY KEY,
    author_urn      TEXT REFERENCES linkedin_authors(urn),
    title           TEXT NOT NULL,
    description     TEXT,
    target_type     TEXT NOT NULL DEFAULT 'growth' CHECK(target_type IN ('growth','leads','authority','hiring','fundraising','community')),
    target_value    TEXT,
    tone            TEXT,
    pillars_json    TEXT,
    status          TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','done','dropped')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_linkedin_goals_author ON linkedin_goals(author_urn, status);

-- Skills / voice / content strategy per author (mirrors social_skill but scoped)
CREATE TABLE IF NOT EXISTS linkedin_skills (
    id              TEXT PRIMARY KEY,
    author_urn      TEXT REFERENCES linkedin_authors(urn),
    category        TEXT NOT NULL CHECK(category IN ('voice','pillar','audience','offer','proof','content_strategy','style_guide')),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(author_urn, category, title)
);
CREATE INDEX IF NOT EXISTS idx_linkedin_skills_author ON linkedin_skills(author_urn, category);

-- Posts: draft/manual (personal) vs scheduled/autopost (company)
CREATE TABLE IF NOT EXISTS linkedin_posts (
    id              TEXT PRIMARY KEY,
    author_urn      TEXT NOT NULL REFERENCES linkedin_authors(urn),
    author_type     TEXT NOT NULL CHECK(author_type IN ('personal','company')),
    commentary      TEXT NOT NULL,
    image_prompt    TEXT,
    image_b64       TEXT,
    image_urn       TEXT,
    image_model     TEXT,
    hashtags_json   TEXT,
    hook            TEXT,
    cta             TEXT,
    pillar          TEXT,
    goal_id         TEXT REFERENCES linkedin_goals(id),
    status          TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','manual','scheduled','publishing','published','failed','archived')),
    scheduled_at    TEXT,
    published_at    TEXT,
    published_urn   TEXT,
    published_url   TEXT,
    error           TEXT,
    model_used      TEXT,
    tokens_used     INTEGER,
    cost_usd        REAL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_linkedin_posts_author_status ON linkedin_posts(author_urn, status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_linkedin_posts_scheduled ON linkedin_posts(status, scheduled_at) WHERE status='scheduled';

-- Stats per post (fetched via memberCreatorPostAnalytics / organizationalEntityShareStatistics)
CREATE TABLE IF NOT EXISTS linkedin_post_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         TEXT NOT NULL REFERENCES linkedin_posts(id),
    impressions     INTEGER DEFAULT 0,
    members_reached INTEGER DEFAULT 0,
    reactions       INTEGER DEFAULT 0,
    comments        INTEGER DEFAULT 0,
    reshares        INTEGER DEFAULT 0,
    saves           INTEGER DEFAULT 0,
    sends           INTEGER DEFAULT 0,
    clicks          INTEGER DEFAULT 0,
    engagement_rate REAL DEFAULT 0,
    fetched_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_linkedin_stats_post ON linkedin_post_stats(post_id, fetched_at);

-- Insights / learning memory (feeds next generation)
CREATE TABLE IF NOT EXISTS linkedin_insights (
    id              TEXT PRIMARY KEY,
    author_urn      TEXT NOT NULL REFERENCES linkedin_authors(urn),
    kind            TEXT NOT NULL CHECK(kind IN ('winner','loser','pattern','recommendation')),
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    evidence_json   TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_linkedin_insights_author ON linkedin_insights(author_urn, created_at);

-- OAuth + linkedin accounts compatibility view (also store raw)
CREATE TABLE IF NOT EXISTS linkedin_accounts (
    id              TEXT PRIMARY KEY,
    author_urn      TEXT NOT NULL REFERENCES linkedin_authors(urn),
    access_token    TEXT NOT NULL,
    refresh_token   TEXT,
    expires_at      TEXT,
    token_type      TEXT DEFAULT 'Bearer',
    scope           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""

# ---------- authors ----------
def create_author(conn: sqlite3.Connection, type: str, urn: str, name: str, vanity_name: str = "") -> str:
    aid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO linkedin_authors (id, type, urn, name, vanity_name) VALUES (?,?,?,?,?)",
        (aid, type, urn, name, vanity_name),
    )
    conn.commit()
    return aid

def upsert_author(conn: sqlite3.Connection, type: str, urn: str, name: str, vanity_name: str = "") -> dict:
    row = conn.execute("SELECT * FROM linkedin_authors WHERE urn=?", (urn,)).fetchone()
    if row:
        conn.execute(
            "UPDATE linkedin_authors SET type=?, name=?, vanity_name=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE urn=?",
            (type, name, vanity_name, urn),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM linkedin_authors WHERE urn=?", (urn,)).fetchone()
        return dict(row)
    aid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO linkedin_authors (id, type, urn, name, vanity_name) VALUES (?,?,?,?,?)",
        (aid, type, urn, name, vanity_name),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM linkedin_authors WHERE id=?", (aid,)).fetchone()
    return dict(row)

def list_authors(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM linkedin_authors ORDER BY type, name").fetchall()
    return [dict(r) for r in rows]

def get_author(conn: sqlite3.Connection, urn: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM linkedin_authors WHERE urn=?", (urn,)).fetchone()
    return dict(row) if row else None

def get_author_by_id(conn: sqlite3.Connection, aid: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM linkedin_authors WHERE id=?", (aid,)).fetchone()
    return dict(row) if row else None

# ---------- goals ----------
def create_goal(conn: sqlite3.Connection, author_urn: str, title: str, description: str = "", target_type: str = "growth", target_value: str = "", tone: str = "", pillars: list[str] | None = None) -> dict:
    gid = uuid.uuid4().hex
    pillars_json = json.dumps(pillars or [])
    conn.execute(
        "INSERT INTO linkedin_goals (id, author_urn, title, description, target_type, target_value, tone, pillars_json) VALUES (?,?,?,?,?,?,?,?)",
        (gid, author_urn, title, description, target_type, target_value, tone, pillars_json),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM linkedin_goals WHERE id=?", (gid,)).fetchone()
    d = dict(row)
    d["pillars"] = json.loads(d["pillars_json"] or "[]")
    return d

def list_goals(conn: sqlite3.Connection, author_urn: str | None = None, status: str = "active") -> list[dict]:
    if author_urn:
        rows = conn.execute("SELECT * FROM linkedin_goals WHERE author_urn=? AND status=? ORDER BY created_at DESC", (author_urn, status)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM linkedin_goals WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["pillars"] = json.loads(d["pillars_json"] or "[]")
        out.append(d)
    return out

def get_goal(conn: sqlite3.Connection, gid: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM linkedin_goals WHERE id=?", (gid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["pillars"] = json.loads(d["pillars_json"] or "[]")
    return d

def update_goal(conn: sqlite3.Connection, gid: str, **fields) -> Optional[dict]:
    allowed = {"title","description","target_type","target_value","tone","status"}
    sets = []
    vals = []
    for k,v in fields.items():
        if k == "pillars":
            sets.append("pillars_json=?")
            vals.append(json.dumps(v))
        elif k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return get_goal(conn, gid)
    sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")
    vals.append(gid)
    conn.execute(f"UPDATE linkedin_goals SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    return get_goal(conn, gid)

def delete_goal(conn: sqlite3.Connection, gid: str) -> bool:
    cur = conn.execute("DELETE FROM linkedin_goals WHERE id=?", (gid,))
    conn.commit()
    return cur.rowcount > 0

# ---------- skills ----------
def save_skill(conn: sqlite3.Connection, author_urn: str, category: str, title: str, content: str) -> dict:
    sid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO linkedin_skills (id, author_urn, category, title, content) VALUES (?,?,?,?,?) "
        "ON CONFLICT(author_urn, category, title) DO UPDATE SET content=excluded.content, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
        (sid, author_urn, category, title, content),
    )
    # fetch the actual row (either inserted or updated)
    row = conn.execute("SELECT * FROM linkedin_skills WHERE author_urn=? AND category=? AND title=?", (author_urn, category, title)).fetchone()
    conn.commit()
    return dict(row)

def list_skills(conn: sqlite3.Connection, author_urn: str | None = None, category: str | None = None) -> list[dict]:
    q = "SELECT * FROM linkedin_skills WHERE 1=1"
    params: list[Any] = []
    if author_urn:
        q += " AND author_urn=?"
        params.append(author_urn)
    if category:
        q += " AND category=?"
        params.append(category)
    q += " ORDER BY author_urn, category, title"
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]

def delete_skill(conn: sqlite3.Connection, sid: str) -> bool:
    cur = conn.execute("DELETE FROM linkedin_skills WHERE id=?", (sid,))
    conn.commit()
    return cur.rowcount > 0

def get_skills_context(conn: sqlite3.Connection, author_urn: str) -> dict[str, list[dict]]:
    """Grouped by category for prompt injection."""
    skills = list_skills(conn, author_urn)
    grouped: dict[str, list[dict]] = {}
    for s in skills:
        grouped.setdefault(s["category"], []).append(s)
    return grouped

# ---------- posts ----------
def create_post(conn: sqlite3.Connection, author_urn: str, author_type: str, commentary: str, **kwargs) -> dict:
    pid = uuid.uuid4().hex
    fields = {
        "id": pid,
        "author_urn": author_urn,
        "author_type": author_type,
        "commentary": commentary,
        "image_prompt": kwargs.get("image_prompt"),
        "image_b64": kwargs.get("image_b64"),
        "image_model": kwargs.get("image_model"),
        "hashtags_json": json.dumps(kwargs.get("hashtags") or []),
        "hook": kwargs.get("hook"),
        "cta": kwargs.get("cta"),
        "pillar": kwargs.get("pillar"),
        "goal_id": kwargs.get("goal_id"),
        "status": kwargs.get("status", "draft"),
        "scheduled_at": kwargs.get("scheduled_at"),
        "model_used": kwargs.get("model_used"),
        "tokens_used": kwargs.get("tokens_used"),
        "cost_usd": kwargs.get("cost_usd"),
    }
    conn.execute(
        "INSERT INTO linkedin_posts (id, author_urn, author_type, commentary, image_prompt, image_b64, image_model, hashtags_json, hook, cta, pillar, goal_id, status, scheduled_at, model_used, tokens_used, cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (fields["id"], fields["author_urn"], fields["author_type"], fields["commentary"], fields["image_prompt"], fields["image_b64"], fields["image_model"], fields["hashtags_json"], fields["hook"], fields["cta"], fields["pillar"], fields["goal_id"], fields["status"], fields["scheduled_at"], fields["model_used"], fields["tokens_used"], fields["cost_usd"]),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM linkedin_posts WHERE id=?", (pid,)).fetchone()
    d = dict(row)
    d["hashtags"] = json.loads(d["hashtags_json"] or "[]")
    return d

def list_posts(conn: sqlite3.Connection, author_urn: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
    q = "SELECT * FROM linkedin_posts WHERE 1=1"
    params: list[Any] = []
    if author_urn:
        q += " AND author_urn=?"
        params.append(author_urn)
    if status:
        q += " AND status=?"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["hashtags"] = json.loads(d["hashtags_json"] or "[]")
        out.append(d)
    return out

def get_post(conn: sqlite3.Connection, pid: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM linkedin_posts WHERE id=?", (pid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["hashtags"] = json.loads(d["hashtags_json"] or "[]")
    return d

def update_post(conn: sqlite3.Connection, pid: str, **fields) -> Optional[dict]:
    allowed = {"commentary","image_prompt","image_b64","image_urn","image_model","hook","cta","pillar","status","scheduled_at","published_at","published_urn","published_url","error","goal_id","hashtags"}
    sets = []
    vals: list[Any] = []
    for k,v in fields.items():
        if k == "hashtags":
            sets.append("hashtags_json=?")
            vals.append(json.dumps(v))
        elif k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return get_post(conn, pid)
    sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')")
    vals.append(pid)
    conn.execute(f"UPDATE linkedin_posts SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    return get_post(conn, pid)

def delete_post(conn: sqlite3.Connection, pid: str) -> bool:
    cur = conn.execute("DELETE FROM linkedin_posts WHERE id=?", (pid,))
    conn.commit()
    return cur.rowcount > 0

def get_scheduled_due(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM linkedin_posts WHERE status='scheduled' AND scheduled_at <= strftime('%Y-%m-%dT%H:%M:%fZ','now') ORDER BY scheduled_at ASC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["hashtags"] = json.loads(d["hashtags_json"] or "[]")
        out.append(d)
    return out

# ---------- stats ----------
def add_stat(conn: sqlite3.Connection, post_id: str, impressions: int = 0, members_reached: int = 0, reactions: int = 0, comments: int = 0, reshares: int = 0, saves: int = 0, sends: int = 0, clicks: int = 0) -> dict:
    total_eng = reactions + comments + reshares
    rate = (total_eng / impressions * 100) if impressions else 0
    cur = conn.execute(
        "INSERT INTO linkedin_post_stats (post_id, impressions, members_reached, reactions, comments, reshares, saves, sends, clicks, engagement_rate) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (post_id, impressions, members_reached, reactions, comments, reshares, saves, sends, clicks, rate),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM linkedin_post_stats WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)

def get_stats(conn: sqlite3.Connection, post_id: str, limit: int = 10) -> list[dict]:
    rows = conn.execute("SELECT * FROM linkedin_post_stats WHERE post_id=? ORDER BY fetched_at DESC LIMIT ?", (post_id, limit)).fetchall()
    return [dict(r) for r in rows]

def get_latest_stat(conn: sqlite3.Connection, post_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM linkedin_post_stats WHERE post_id=? ORDER BY fetched_at DESC LIMIT 1", (post_id,)).fetchone()
    return dict(row) if row else None

# ---------- insights ----------
def add_insight(conn: sqlite3.Connection, author_urn: str, kind: str, title: str, body: str, evidence: dict | None = None) -> dict:
    iid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO linkedin_insights (id, author_urn, kind, title, body, evidence_json) VALUES (?,?,?,?,?,?)",
        (iid, author_urn, kind, title, body, json.dumps(evidence or {})),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM linkedin_insights WHERE id=?", (iid,)).fetchone()
    d = dict(row)
    d["evidence"] = json.loads(d["evidence_json"] or "{}")
    return d

def list_insights(conn: sqlite3.Connection, author_urn: str | None = None, limit: int = 20) -> list[dict]:
    if author_urn:
        rows = conn.execute("SELECT * FROM linkedin_insights WHERE author_urn=? ORDER BY created_at DESC LIMIT ?", (author_urn, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM linkedin_insights ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["evidence"] = json.loads(d["evidence_json"] or "{}")
        out.append(d)
    return out

# Ensure on import side: call apply_schema
def ensure_linkedin_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(LINKEDIN_SCHEMA)
    conn.commit()
