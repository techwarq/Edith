"""SQLite connection, PRAGMAs, schema DDL, integrity/FTS5 sanity checks."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ended_at      TEXT,
    model         TEXT,
    message_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    role            TEXT NOT NULL CHECK(role IN ('user','assistant','tool','system')),
    content         TEXT,
    tool_calls_json TEXT,
    tool_call_id    TEXT,
    tool_name       TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS user_profile (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    key                TEXT NOT NULL UNIQUE,
    value              TEXT NOT NULL,
    category           TEXT,
    source_message_id  INTEGER REFERENCES messages(id),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name   TEXT NOT NULL,
    args_json   TEXT NOT NULL,
    preview     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS device_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT NOT NULL UNIQUE,
    platform   TEXT NOT NULL DEFAULT 'android',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS health_metrics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL,
    date       TEXT NOT NULL,
    value      REAL NOT NULL,
    unit       TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(type, date)
);

CREATE TABLE IF NOT EXISTS traces (
    id                 TEXT PRIMARY KEY,
    session_id         TEXT REFERENCES sessions(id),
    kind               TEXT NOT NULL DEFAULT 'turn' CHECK(kind IN ('turn','eval')),
    input              TEXT,
    output             TEXT,
    status             TEXT NOT NULL DEFAULT 'ok' CHECK(status IN ('ok','error')),
    error              TEXT,
    started_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ended_at           TEXT,
    duration_ms        REAL,
    prompt_tokens      INTEGER NOT NULL DEFAULT 0,
    completion_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd           REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id, started_at);
CREATE INDEX IF NOT EXISTS idx_traces_started ON traces(started_at);

CREATE TABLE IF NOT EXISTS spans (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id           TEXT NOT NULL REFERENCES traces(id),
    kind               TEXT NOT NULL CHECK(kind IN ('llm','tool')),
    name               TEXT NOT NULL,
    input              TEXT,
    output             TEXT,
    status             TEXT NOT NULL DEFAULT 'ok' CHECK(status IN ('ok','error')),
    error              TEXT,
    started_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    duration_ms        REAL,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    cost_usd           REAL
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id, id);

CREATE TABLE IF NOT EXISTS eval_cases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    input        TEXT NOT NULL,
    rubric       TEXT NOT NULL,
    expect_tools TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id          TEXT PRIMARY KEY,
    model       TEXT,
    started_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ended_at    TEXT
);

CREATE TABLE IF NOT EXISTS eval_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES eval_runs(id),
    case_id         INTEGER NOT NULL REFERENCES eval_cases(id),
    trace_id        TEXT REFERENCES traces(id),
    score           REAL NOT NULL,
    passed          INTEGER NOT NULL,
    judge_reasoning TEXT,
    tools_called    TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id);

CREATE TABLE IF NOT EXISTS goals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT,
    target_date  TEXT,
    status       TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','done','dropped')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS goal_milestones (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id      INTEGER NOT NULL REFERENCES goals(id),
    title        TEXT NOT NULL,
    target_date  TEXT,
    done         INTEGER NOT NULL DEFAULT 0,
    done_at      TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_milestones_goal ON goal_milestones(goal_id, sort_order);

CREATE TABLE IF NOT EXISTS insights (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL DEFAULT 'insight' CHECK(kind IN ('insight','goal_update','observation')),
    title        TEXT NOT NULL,
    body         TEXT,
    goal_id      INTEGER REFERENCES goals(id),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    seen_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_insights_seen ON insights(seen_at);

CREATE TABLE IF NOT EXISTS todos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    note         TEXT,
    status       TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','in_progress','done')),
    due_date     TEXT,
    goal_id      INTEGER REFERENCES goals(id),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status, due_date);

-- User-added MCP (Model Context Protocol) servers, wired in from the web
-- dashboard's Integrations tab — no code change/redeploy needed to add one.
-- Only stdio-based servers (command + args + optional env) are supported;
-- their tools are discovered once at process startup and merged into the
-- normal ToolRegistry (see edith/tools/mcp_client.py), so a server added here
-- takes effect on the next restart, not immediately.
CREATE TABLE IF NOT EXISTS mcp_servers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    command      TEXT NOT NULL,
    args_json    TEXT NOT NULL DEFAULT '[]',
    env_json     TEXT,
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages
WHEN new.content IS NOT NULL BEGIN
  INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages
WHEN old.content IS NOT NULL BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_au_delete AFTER UPDATE ON messages
WHEN old.content IS NOT NULL BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_au_insert AFTER UPDATE ON messages
WHEN new.content IS NOT NULL BEGIN
  INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


class DatabaseError(RuntimeError):
    pass


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: server.py dispatches blocking DB calls via asyncio.to_thread(),
    # which runs each call on a different worker thread than the one that opened this connection.
    # Safe for our access pattern (single personal user, low concurrency, WAL mode + busy_timeout
    # below already serialize writes) — CLI usage is single-threaded anyway so this is a no-op there.
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")

    _check_fts5_support(conn)
    conn.executescript(SCHEMA)
    _check_integrity(conn)

    return conn


def _check_fts5_support(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_canary USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts5_canary")
    except sqlite3.OperationalError as e:
        raise DatabaseError(
            "This Python's sqlite3 module was built without FTS5 support. "
            "Reinstall Python via a build that links a modern SQLite "
            "(e.g. `brew install python@3.11` or pyenv with FTS5 enabled)."
        ) from e


def _check_integrity(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    if row is None or row[0] != "ok":
        raise DatabaseError(
            f"Database integrity check failed: {row[0] if row else 'unknown'}. "
            f"The edith.db file may be corrupted."
        )
