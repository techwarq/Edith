"""Job-applications API — the desktop/web dashboard's Jobs tab. Same shared-
token auth pattern as edith/goals/api.py and server.py; every DB call runs on
a worker thread via asyncio.to_thread, matching every other endpoint in the
project.

Approve/reject reuse the exact same pending_actions + EXECUTORS mechanism as
the CLI's /approve (edith/commands.py) — this is what makes the first
monitored batch reviewable from the dashboard, not just the terminal.
"""

import asyncio
import sqlite3
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from edith.bootstrap import EXECUTORS
from edith.config import JOBS_DAILY_CAP
from edith.integrations.google import auth as google_auth
from edith.memory import job_applications_store as jobs_store
from edith.memory import store
from edith.tools.growth.job_applications import AUTONOMOUS_KEY, JOBS_CONFIG_CATEGORY


def build_router(conn: sqlite3.Connection, api_token: str) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _check_token(token: str) -> Optional[JSONResponse]:
        if not api_token or token != api_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    @router.get("/job-applications", response_model=None)
    async def list_job_applications(token: str = "", status: Optional[str] = None) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        applications = await asyncio.to_thread(jobs_store.list_applications, conn, status)
        return JSONResponse({"applications": applications})

    @router.get("/job-applications/{application_id}", response_model=None)
    async def get_job_application(application_id: int, token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        application = await asyncio.to_thread(jobs_store.get_application, conn, application_id)
        if application is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(application)

    def _resolve(application_id: int, target_status: str) -> Optional[dict]:
        application = jobs_store.get_application(conn, application_id)
        if application is None or application.get("pending_action_id") is None:
            return None

        resolved = store.resolve_pending_action(conn, application["pending_action_id"], target_status)
        if resolved is None:
            return None

        if target_status == "rejected":
            jobs_store.update_application(conn, application_id, status="failed", error="rejected by user")
            return jobs_store.get_application(conn, application_id)

        executor = EXECUTORS.get(resolved["tool_name"])
        if executor is None:
            jobs_store.update_application(conn, application_id, status="failed", error=f"no executor for {resolved['tool_name']}")
            return jobs_store.get_application(conn, application_id)

        google_creds = google_auth.get_credentials()
        result = executor(google_creds, resolved["args"])
        ok = not result.startswith("ERROR")
        new_status = "sent" if resolved["tool_name"] == "send_email" else "applied"
        jobs_store.update_application(
            conn, application_id,
            status=new_status if ok else "failed",
            error=None if ok else result,
        )
        return jobs_store.get_application(conn, application_id)

    @router.post("/job-applications/{application_id}/approve", response_model=None)
    async def approve_job_application(application_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        application = await asyncio.to_thread(_resolve, application_id, "approved")
        if application is None:
            return JSONResponse({"error": "no pending action for this application"}, status_code=404)
        return JSONResponse(application)

    @router.post("/job-applications/{application_id}/reject", response_model=None)
    async def reject_job_application(application_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        application = await asyncio.to_thread(_resolve, application_id, "rejected")
        if application is None:
            return JSONResponse({"error": "no pending action for this application"}, status_code=404)
        return JSONResponse(application)

    @router.get("/jobs-config", response_model=None)
    async def get_jobs_config(token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err

        def _read() -> dict:
            return {
                "autonomous_enabled": store.get_fact(conn, AUTONOMOUS_KEY) == "true",
                "daily_cap": JOBS_DAILY_CAP,
                "sent_today": jobs_store.count_sent_today(conn),
            }

        return JSONResponse(await asyncio.to_thread(_read))

    @router.post("/jobs-config", response_model=None)
    async def set_jobs_config(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        if "autonomous_enabled" not in body:
            return JSONResponse({"error": "autonomous_enabled is required"}, status_code=400)

        def _write() -> dict:
            store.save_fact(
                conn, key=AUTONOMOUS_KEY, value="true" if body["autonomous_enabled"] else "false",
                category=JOBS_CONFIG_CATEGORY,
            )
            return {
                "autonomous_enabled": store.get_fact(conn, AUTONOMOUS_KEY) == "true",
                "daily_cap": JOBS_DAILY_CAP,
                "sent_today": jobs_store.count_sent_today(conn),
            }

        return JSONResponse(await asyncio.to_thread(_write))

    return router
