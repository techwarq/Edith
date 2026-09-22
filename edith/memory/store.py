"""CRUD for sessions/messages/user_profile; whole-turn-aware context trimming."""

import json
import sqlite3
import uuid
from typing import Any, Optional


# ---------------------------------------------------------------------------
# sessions / meta
# ---------------------------------------------------------------------------

def create_session(conn: sqlite3.Connection, model: str) -> str:
    session_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO sessions (id, model) VALUES (?, ?)", (session_id, model)
    )
    set_meta(conn, "last_session_id", session_id)
    return session_id


def get_last_session_id(conn: sqlite3.Connection) -> Optional[str]:
    return get_meta(conn, "last_session_id")


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


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


# ---------------------------------------------------------------------------
# user_profile (core memory)
# ---------------------------------------------------------------------------

def save_fact(
    conn: sqlite3.Connection,
    key: str,
    value: str,
    category: Optional[str] = None,
    source_message_id: Optional[int] = None,
) -> None:
    conn.execute(
        "INSERT INTO user_profile (key, value, category, source_message_id) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET "
        "value = excluded.value, category = excluded.category, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
        (key, value, category, source_message_id),
    )


def forget_fact(conn: sqlite3.Connection, key: str) -> bool:
    cur = conn.execute("DELETE FROM user_profile WHERE key = ?", (key,))
    return cur.rowcount > 0


def get_fact(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM user_profile WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def get_all_facts(conn: sqlite3.Connection) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT key, value, category FROM user_profile ORDER BY category, key"
    ).fetchall()
    return [dict(r) for r in rows]


def get_facts_by_category(conn: sqlite3.Connection, category: str) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT key, value, category FROM user_profile WHERE category = ? ORDER BY key",
        (category,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_or_create_jobs_session(conn: sqlite3.Connection, model: str) -> str:
    """Dedicated session for scheduled Temporal job output (nightly reflection, schedule_job
    runs) — separate from create_session() so it never touches "last_session_id" meta, which
    would otherwise hijack the interactive CLI/server session on next launch."""
    session_id = get_meta(conn, "jobs_session_id")
    if session_id and session_exists(conn, session_id):
        return session_id
    session_id = uuid.uuid4().hex
    conn.execute("INSERT INTO sessions (id, model) VALUES (?, ?)", (session_id, model))
    set_meta(conn, "jobs_session_id", session_id)
    return session_id


# ---------------------------------------------------------------------------
# device_tokens (FCM push notification targets — see edith/push.py)
# ---------------------------------------------------------------------------

def save_device_token(conn: sqlite3.Connection, token: str, platform: str = "android") -> None:
    conn.execute(
        "INSERT INTO device_tokens (token, platform) VALUES (?, ?) "
        "ON CONFLICT(token) DO NOTHING",
        (token, platform),
    )


def list_device_tokens(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT token FROM device_tokens").fetchall()
    return [r["token"] for r in rows]


def delete_device_token(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM device_tokens WHERE token = ?", (token,))


# ---------------------------------------------------------------------------
# pending_actions (hard gate for risky tool actions — see edith/integrations/google/*)
# ---------------------------------------------------------------------------

def queue_pending_action(
    conn: sqlite3.Connection, tool_name: str, args: dict, preview: str
) -> int:
    cur = conn.execute(
        "INSERT INTO pending_actions (tool_name, args_json, preview) VALUES (?, ?, ?)",
        (tool_name, json.dumps(args), preview),
    )
    return cur.lastrowid


def get_pending_actions(conn: sqlite3.Connection, status: str = "pending") -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, tool_name, args_json, preview, status, created_at FROM pending_actions "
        "WHERE status = ? ORDER BY id ASC",
        (status,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "tool_name": r["tool_name"],
            "args": json.loads(r["args_json"]),
            "preview": r["preview"],
            "status": r["status"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def resolve_pending_action(conn: sqlite3.Connection, action_id: int, status: str) -> Optional[dict[str, Any]]:
    """Marks the action resolved and returns its row (tool_name/args) so the
    caller can dispatch to the right executor. Returns None if the id doesn't
    exist or isn't still pending."""
    row = conn.execute(
        "SELECT id, tool_name, args_json FROM pending_actions WHERE id = ? AND status = 'pending'",
        (action_id,),
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE pending_actions SET status = ?, resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
        (status, action_id),
    )
    return {"id": row["id"], "tool_name": row["tool_name"], "args": json.loads(row["args_json"])}
