"""Working + episodic memory: sessions, messages, whole-turn context trimming, and
FTS5 keyword search over all past messages."""

import json
import sqlite3
import uuid
from typing import Any, Optional

from edith.memory.records import system


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

def create_session(conn: sqlite3.Connection, model: str) -> str:
    session_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO sessions (id, model) VALUES (?, ?)", (session_id, model)
    )
    system.set_setting(conn, "last_session_id", session_id)
    return session_id


def get_last_session_id(conn: sqlite3.Connection) -> Optional[str]:
    return system.get_setting(conn, "last_session_id")


def session_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row is not None


def end_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "UPDATE sessions SET ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
        (session_id,),
    )


def any_session_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM sessions LIMIT 1").fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------

def add_message(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: Optional[str] = None,
    tool_calls: Optional[list[dict]] = None,
    tool_call_id: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> int:
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
    cur = conn.execute(
        "INSERT INTO messages (session_id, role, content, tool_calls_json, tool_call_id, tool_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, role, content, tool_calls_json, tool_call_id, tool_name),
    )
    conn.execute(
        "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
        (session_id,),
    )
    return cur.lastrowid


def _row_to_openai_message(row: sqlite3.Row) -> dict[str, Any]:
    content = row["content"]
    if row["role"] == "assistant" and content is None:
        # Historical tool-calls-only assistant messages were persisted with NULL
        # content (valid then) — replaying that NULL as-is 400s against Alibaba's
        # DashScope backend (Qwen models via OpenRouter). See the matching write-
        # side fix in edith/llm/client.py's run_completion_with_tools.
        content = ""
    msg: dict[str, Any] = {"role": row["role"], "content": content}
    if row["role"] == "assistant" and row["tool_calls_json"]:
        msg["tool_calls"] = json.loads(row["tool_calls_json"])
    if row["role"] == "tool":
        msg["tool_call_id"] = row["tool_call_id"]
        msg["name"] = row["tool_name"]
    return msg


def get_working_messages(
    conn: sqlite3.Connection, session_id: str, max_turns: int
) -> list[dict[str, Any]]:
    """Return recent conversation history as OpenAI-format messages, trimmed
    to whole turns (a turn = one user message + everything up to the next
    user message) so tool_calls/tool pairs are never split."""
    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()

    turns: list[list[sqlite3.Row]] = []
    for row in rows:
        if row["role"] == "user" or not turns:
            turns.append([row])
        else:
            turns[-1].append(row)

    kept = turns[-max_turns:] if max_turns > 0 else turns
    messages = [_row_to_openai_message(r) for turn in kept for r in turn]
    return messages


def get_recent_assistant_replies(
    conn: sqlite3.Connection, session_id: str, limit: int
) -> list[dict[str, Any]]:
    """Most recent assistant replies (with content) from a session, newest first —
    used by the /jobs command to show recent scheduled-job/nightly-reflection output."""
    rows = conn.execute(
        "SELECT created_at, content FROM messages "
        "WHERE session_id = ? AND role = 'assistant' AND content IS NOT NULL AND content != '' "
        "ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_or_create_jobs_session(conn: sqlite3.Connection, model: str) -> str:
    """Dedicated session for scheduled Temporal job output (nightly reflection, schedule_job
    runs) — separate from create_session() so it never touches "last_session_id" meta, which
    would otherwise hijack the interactive CLI/server session on next launch."""
    session_id = system.get_setting(conn, "jobs_session_id")
    if session_id and session_exists(conn, session_id):
        return session_id
    session_id = uuid.uuid4().hex
    conn.execute("INSERT INTO sessions (id, model) VALUES (?, ?)", (session_id, model))
    system.set_setting(conn, "jobs_session_id", session_id)
    return session_id


# ---------------------------------------------------------------------------
# keyword search (FTS5)
# ---------------------------------------------------------------------------

def _fts_escape(query: str) -> str:
    """Wrap free-text input in quotes per-token so FTS5 special characters
    (AND, OR, NOT, *, -, ") in user input don't break the query syntax."""
    tokens = query.split()
    escaped = ['"{}"'.format(t.replace('"', '""')) for t in tokens]
    return " ".join(escaped) if escaped else '""'


def search_history(
    conn: sqlite3.Connection, query: str, limit: int = 10
) -> list[dict[str, str]]:
    fts_query = _fts_escape(query)
    rows = conn.execute(
        """
        SELECT m.id, m.session_id, m.role, m.content, m.created_at
        FROM messages_fts
        JOIN messages m ON m.id = messages_fts.rowid
        WHERE messages_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (fts_query, limit),
    ).fetchall()
    return [dict(r) for r in rows]
