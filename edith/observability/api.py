"""Observability API — spending, traces, and evals endpoints. Mounted into
server.py's FastAPI app via build_router(), same token-auth pattern as every
other endpoint there (see server.py's _unauthorized/API_TOKEN): a bare
personal-use API, not multi-tenant, so a single shared token is enough.

Read endpoints (spending/traces/performance/tools/eval listings) take the
token as a query param since they're GETs. The one endpoint that does real
work — POST .../evals/run, which drives the live agent through OpenRouter/
Gemini — takes it in the JSON body like server.py's other POSTs, and runs on
a worker thread via asyncio.to_thread since it's a slow blocking call.
"""

import asyncio
import sqlite3
from typing import Optional

import openai
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from edith.agent import Agent
from edith.observability import evals, queries


def build_router(
    conn: sqlite3.Connection,
    agent: Agent,
    judge_client: openai.OpenAI,
    judge_model: str,
    api_token: str,
) -> APIRouter:
    router = APIRouter(prefix="/api/observability")

    def _check_token(token: str) -> Optional[JSONResponse]:
        if not api_token or token != api_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    @router.get("/spending", response_model=None)
    async def spending(token: str = "", days: Optional[int] = 30) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err

        def _fetch() -> dict:
            return {
                "totals": queries.spending_totals(conn, days),
                "by_day": queries.spending_by_day(conn, days or 30),
                "by_model": queries.spending_by_model(conn, days),
                "by_session": queries.spending_by_session(conn),
            }

        return JSONResponse(await asyncio.to_thread(_fetch))

    @router.get("/performance", response_model=None)
    async def performance(token: str = "", days: int = 7) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        overview = await asyncio.to_thread(queries.performance_overview, conn, days)
        return JSONResponse(overview)

    @router.get("/performance/trend", response_model=None)
    async def performance_trend(token: str = "", days: int = 30) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        trend = await asyncio.to_thread(queries.performance_trend, conn, days)
        return JSONResponse({"trend": trend})

    @router.get("/tools", response_model=None)
    async def tools(token: str = "", days: Optional[int] = 30) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        stats = await asyncio.to_thread(queries.tool_stats, conn, days)
        return JSONResponse({"tools": stats})

    @router.get("/traces", response_model=None)
    async def list_traces(
        token: str = "",
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        traces = await asyncio.to_thread(queries.list_traces, conn, session_id, kind, status, limit, offset)
        return JSONResponse({"traces": traces})

    @router.get("/traces/{trace_id}", response_model=None)
    async def get_trace(trace_id: str, token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        trace = await asyncio.to_thread(queries.get_trace, conn, trace_id)
        if trace is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(trace)

    @router.get("/evals/cases", response_model=None)
    async def list_eval_cases(token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        cases = await asyncio.to_thread(queries.list_eval_cases, conn)
        return JSONResponse({"cases": cases})

    @router.get("/evals/runs", response_model=None)
    async def list_eval_runs(token: str = "", limit: int = 20) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        runs = await asyncio.to_thread(queries.list_eval_runs, conn, limit)
        return JSONResponse({"runs": runs})

    @router.get("/evals/trend", response_model=None)
    async def eval_run_trend(token: str = "", limit: int = 30) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        trend = await asyncio.to_thread(queries.eval_run_trend, conn, limit)
        return JSONResponse({"trend": trend})

    @router.get("/evals/cases/{case_id}/trend", response_model=None)
    async def eval_case_trend(case_id: int, token: str = "", limit: int = 30) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        trend = await asyncio.to_thread(queries.eval_case_trend, conn, case_id, limit)
        return JSONResponse({"trend": trend})

    @router.get("/evals/runs/{run_id}", response_model=None)
    async def get_eval_run(run_id: str, token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        run = await asyncio.to_thread(queries.get_eval_run, conn, run_id)
        if run is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(run)

    @router.post("/evals/run", response_model=None)
    async def run_evals(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        case_ids = body.get("case_ids")
        result = await asyncio.to_thread(evals.run_eval_suite, conn, agent, judge_client, judge_model, case_ids)
        return JSONResponse(result)

    return router

