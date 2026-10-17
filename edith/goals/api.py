"""Goals + insights API — the desktop/web dashboard's "what am I working
toward, what does Edith want to show me" surface. Same shared-token auth
pattern as server.py and edith/observability/api.py; every DB call runs on a
worker thread via asyncio.to_thread, matching every other endpoint in the
project (see server.py's module docstring for why).
"""

import asyncio
import sqlite3
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from edith.memory.records import planning


def build_router(conn: sqlite3.Connection, api_token: str) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _check_token(token: str) -> Optional[JSONResponse]:
        if not api_token or token != api_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    # -- goals ----------------------------------------------------------

    @router.get("/goals", response_model=None)
    async def list_goals(token: str = "", status: Optional[str] = None) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        goals = await asyncio.to_thread(planning.list_goals, conn, status)
        return JSONResponse({"goals": goals})

    @router.post("/goals", response_model=None)
    async def create_goal(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        title = (body.get("title") or "").strip()
        if not title:
            return JSONResponse({"error": "title is required"}, status_code=400)

        def _create() -> dict:
            goal_id = planning.create_goal(conn, title, body.get("description") or None, body.get("target_date") or None)
            return planning.get_goal(conn, goal_id)

        return JSONResponse(await asyncio.to_thread(_create))

    @router.get("/goals/{goal_id}", response_model=None)
    async def get_goal(goal_id: int, token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        goal = await asyncio.to_thread(planning.get_goal, conn, goal_id)
        if goal is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(goal)

    @router.post("/goals/{goal_id}/update", response_model=None)
    async def update_goal(goal_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err

        def _update() -> Optional[dict]:
            planning.update_goal(
                conn,
                goal_id,
                title=body.get("title"),
                description=body.get("description"),
                target_date=body.get("target_date"),
                status=body.get("status"),
            )
            return planning.get_goal(conn, goal_id)

        goal = await asyncio.to_thread(_update)
        if goal is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(goal)

    @router.post("/goals/{goal_id}/delete", response_model=None)
    async def delete_goal(goal_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        ok = await asyncio.to_thread(planning.delete_goal, conn, goal_id)
        return JSONResponse({"ok": ok})

    # -- milestones -------------------------------------------------------

    @router.post("/goals/{goal_id}/milestones", response_model=None)
    async def add_milestone(goal_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        title = (body.get("title") or "").strip()
        if not title:
            return JSONResponse({"error": "title is required"}, status_code=400)

        def _add() -> Optional[int]:
            if planning.get_goal(conn, goal_id) is None:
                return None
            return planning.add_milestone(conn, goal_id, title, body.get("target_date") or None)

        milestone_id = await asyncio.to_thread(_add)
        if milestone_id is None:
            return JSONResponse({"error": "goal not found"}, status_code=404)
        return JSONResponse({"id": milestone_id})

    @router.post("/milestones/{milestone_id}/complete", response_model=None)
    async def complete_milestone(milestone_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        done = bool(body.get("done", True))
        ok = await asyncio.to_thread(planning.set_milestone_done, conn, milestone_id, done)
        return JSONResponse({"ok": ok})

    # -- insights -----------------------------------------------------------

    @router.get("/insights", response_model=None)
    async def list_insights(token: str = "", unseen_only: bool = True, limit: int = 50) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        insights = await asyncio.to_thread(planning.list_insights, conn, unseen_only, limit)
        return JSONResponse({"insights": insights})

    @router.post("/insights/{insight_id}/dismiss", response_model=None)
    async def dismiss_insight(insight_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        ok = await asyncio.to_thread(planning.dismiss_insight, conn, insight_id)
        return JSONResponse({"ok": ok})

    return router
