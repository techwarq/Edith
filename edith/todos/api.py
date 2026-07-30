"""Todos API — the desktop/web dashboard's Todos tab. Same shared-token auth
pattern as edith/goals/api.py and server.py; every DB call runs on a worker
thread via asyncio.to_thread, matching every other endpoint in the project.
"""

import asyncio
import sqlite3
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from edith.memory import todos_store


def build_router(conn: sqlite3.Connection, api_token: str) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _check_token(token: str) -> Optional[JSONResponse]:
        if not api_token or token != api_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    @router.get("/todos", response_model=None)
    async def list_todos(token: str = "", status: Optional[str] = None) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        todos = await asyncio.to_thread(todos_store.list_todos, conn, status)
        return JSONResponse({"todos": todos})

    @router.post("/todos", response_model=None)
    async def create_todo(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        title = (body.get("title") or "").strip()
        if not title:
            return JSONResponse({"error": "title is required"}, status_code=400)

        def _create() -> dict:
            todo_id = todos_store.create_todo(
                conn, title, body.get("note") or None, body.get("due_date") or None, body.get("goal_id") or None
            )
            return todos_store.get_todo(conn, todo_id)

        return JSONResponse(await asyncio.to_thread(_create))

    @router.post("/todos/{todo_id}/update", response_model=None)
    async def update_todo(todo_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err

        def _update() -> Optional[dict]:
            todos_store.update_todo(conn, todo_id, status=body.get("status"), note=body.get("note") or None)
            return todos_store.get_todo(conn, todo_id)

        todo = await asyncio.to_thread(_update)
        if todo is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(todo)

    @router.post("/todos/{todo_id}/delete", response_model=None)
    async def delete_todo(todo_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        ok = await asyncio.to_thread(todos_store.delete_todo, conn, todo_id)
        return JSONResponse({"ok": ok})

    return router
