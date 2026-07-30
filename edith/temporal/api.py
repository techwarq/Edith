"""Deep-research API — backs the dashboard's Insights tab "Run deep research"
button. Starting a run just kicks off DeepResearchWorkflow on Temporal Cloud
(see edith/temporal/schedules.py); the actual 3-round overnight research runs
on the Railway-hosted worker, not in this request. Recent-output re-reads the
same jobs-session assistant replies the /jobs chat command already surfaces —
deep research output isn't tagged separately from other scheduled-job output,
so this shows the same feed, not a deep-research-only filter.
"""

import asyncio
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from edith.config import DEEP_RESEARCH_BUDGET_USD, DEEP_RESEARCH_SLEEP_HOURS, Settings
from edith.memory import store
from edith.temporal import schedules
from edith.temporal.client import TemporalNotConfigured, get_client


def build_router(conn: sqlite3.Connection, settings: Settings, api_token: str) -> APIRouter:
    router = APIRouter(prefix="/api/deep-research", tags=["deep-research"])

    def _check_token(token: str) -> JSONResponse | None:
        if token != api_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    @router.post("/run", response_model=None)
    async def run(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        try:
            client = await get_client(settings)
            await schedules.start_deep_research(client, DEEP_RESEARCH_BUDGET_USD, DEEP_RESEARCH_SLEEP_HOURS)
        except TemporalNotConfigured as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse(
            {"started": True, "budget_usd": DEEP_RESEARCH_BUDGET_USD, "sleep_hours": DEEP_RESEARCH_SLEEP_HOURS}
        )

    @router.get("/runs", response_model=None)
    async def runs(token: str = "", limit: int = 5) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        jobs_session_id = await asyncio.to_thread(store.get_or_create_jobs_session, conn, settings.model)
        replies = await asyncio.to_thread(store.get_recent_assistant_replies, conn, jobs_session_id, limit)
        return JSONResponse({"replies": replies})

    return router
