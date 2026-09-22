"""CRUD for mcp_servers — user-configured MCP servers, added from the web
dashboard rather than code (see edith/tools/system/mcp_client.py for how they get
turned into callable tools, and edith/mcp/api.py for the HTTP surface this
backs).
"""

import json
import sqlite3
from typing import Any, Optional


def list_servers(conn: sqlite3.Connection, enabled_only: bool = False) -> list[dict[str, Any]]:
    if enabled_only:
        rows = conn.execute("SELECT * FROM mcp_servers WHERE enabled = 1 ORDER BY created_at ASC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM mcp_servers ORDER BY created_at ASC").fetchall()
    return [dict(r) for r in rows]


def get_server(conn: sqlite3.Connection, server_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    return dict(row) if row else None


def create_server(
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


def set_enabled(conn: sqlite3.Connection, server_id: int, enabled: bool) -> bool:
    cur = conn.execute("UPDATE mcp_servers SET enabled = ? WHERE id = ?", (int(enabled), server_id))
    return cur.rowcount > 0


def delete_server(conn: sqlite3.Connection, server_id: int) -> bool:
    cur = conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
    return cur.rowcount > 0
