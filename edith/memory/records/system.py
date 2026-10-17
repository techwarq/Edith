"""App state that isn't memory: key/value settings (tracked URLs, repos, job sources,
flags, internal cursors), pending approvals, push device tokens, and MCP servers."""

import json
import sqlite3
from typing import Any, Optional


# ---------------------------------------------------------------------------
# settings (key/value, optional category)
# ---------------------------------------------------------------------------

def set_setting(conn: sqlite3.Connection, key: str, value: str, category: Optional[str] = None) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, category) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, category = excluded.category, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
        (key, value, category),
    )


def get_setting(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def delete_setting(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("DELETE FROM settings WHERE key = ?", (key,)).rowcount > 0


def list_settings(conn: sqlite3.Connection, category: str) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT key, value, category FROM settings WHERE category = ? ORDER BY key", (category,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# pending_actions (hard gate for risky tool actions)
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


# ---------------------------------------------------------------------------
# device_tokens (FCM push targets)
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
# mcp_servers
# ---------------------------------------------------------------------------

def list_mcp_servers(conn: sqlite3.Connection, enabled_only: bool = False) -> list[dict[str, Any]]:
    if enabled_only:
        rows = conn.execute("SELECT * FROM mcp_servers WHERE enabled = 1 ORDER BY created_at ASC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM mcp_servers ORDER BY created_at ASC").fetchall()
    return [dict(r) for r in rows]


def get_mcp_server(conn: sqlite3.Connection, server_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    return dict(row) if row else None


def create_mcp_server(
    conn: sqlite3.Connection,
    name: str,
    command: str,
    args: Optional[list[str]] = None,
    env: Optional[dict[str, str]] = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO mcp_servers (name, command, args_json, env_json) VALUES (?, ?, ?, ?)",
        (name, command, json.dumps(args or []), json.dumps(env) if env else None),
    )
    return cur.lastrowid


def set_mcp_server_enabled(conn: sqlite3.Connection, server_id: int, enabled: bool) -> bool:
    cur = conn.execute("UPDATE mcp_servers SET enabled = ? WHERE id = ?", (int(enabled), server_id))
    return cur.rowcount > 0


def delete_mcp_server(conn: sqlite3.Connection, server_id: int) -> bool:
    cur = conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
    return cur.rowcount > 0
