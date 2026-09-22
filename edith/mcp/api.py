"""MCP servers API — the web dashboard's Integrations tab. Lets the user add/
remove/enable stdio-based MCP servers without touching code (see
edith/tools/system/mcp_client.py for how an enabled server's tools get discovered
and merged into the agent's ToolRegistry). Same shared-token auth pattern as
edith/goals/api.py and edith/todos/api.py.

A server added or toggled here takes effect on the next process restart, not
immediately — tools are only discovered once, at registry-build time.
"""

import asyncio
import sqlite3
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from edith.memory import mcp_store


def build_router(conn: sqlite3.Connection, api_token: str) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _check_token(token: str) -> Optional[JSONResponse]:
        if not api_token or token != api_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    @router.get("/mcp/servers", response_model=None)
    async def list_servers(token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        servers = await asyncio.to_thread(mcp_store.list_servers, conn)
        return JSONResponse({"servers": servers})

    @router.post("/mcp/servers", response_model=None)
    async def create_server(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        name = (body.get("name") or "").strip()
        command = (body.get("command") or "").strip()
        if not name or not command:
            return JSONResponse({"error": "name and command are required"}, status_code=400)
        args = body.get("args") or []
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            return JSONResponse({"error": "args must be a list of strings"}, status_code=400)
        env = body.get("env") or None
        if env is not None and (not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values())):
            return JSONResponse({"error": "env must be an object of string values"}, status_code=400)

        def _create() -> dict:
            server_id = mcp_store.create_server(conn, name, command, args, env)
            return mcp_store.get_server(conn, server_id)

        try:
            server = await asyncio.to_thread(_create)
        except sqlite3.IntegrityError:
            return JSONResponse({"error": f"a server named {name!r} already exists"}, status_code=409)
        return JSONResponse(server)

    @router.post("/mcp/servers/{server_id}/toggle", response_model=None)
    async def toggle_server(server_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        enabled = bool(body.get("enabled"))
        ok = await asyncio.to_thread(mcp_store.set_enabled, conn, server_id, enabled)
        if not ok:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(await asyncio.to_thread(mcp_store.get_server, conn, server_id))

    @router.post("/mcp/servers/{server_id}/delete", response_model=None)
    async def delete_server(server_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        ok = await asyncio.to_thread(mcp_store.delete_server, conn, server_id)
        return JSONResponse({"ok": ok})

    return router
