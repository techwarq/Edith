import asyncio
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from edith.config import Settings
from edith.integrations.google import auth as google_auth
from edith.integrations.google import gmail
from edith.memory import startup_leads_store as leads_store
from edith.startup_finder import email_draft, finder, llm

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _location(v: Any) -> Optional[str]:
    items = v if isinstance(v, list) else str(v or "").split(",")
    joined = ", ".join(str(i).strip() for i in items if str(i).strip())
    return joined or None


def _int_or_none(v: Any) -> Optional[int]:
    return int(v) if v not in (None, "", 0) else None


def build_router(conn: sqlite3.Connection, settings: Settings, genai_client: Any, api_token: str) -> APIRouter:
    router = APIRouter(prefix="/api/startup-finder")
    llm_client = llm.from_settings(settings) or genai_client
    model = getattr(settings, "startup_finder_model", "") if llm_client is not genai_client else settings.gemini_grounding_model
    lock = asyncio.Lock()

    def _check_token(token: str) -> Optional[JSONResponse]:
        if not api_token or token != api_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    @router.post("/run", response_model=None)
    async def run(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        try:
            count = int(body.get("count", 10))
        except (TypeError, ValueError):
            return JSONResponse({"error": "count must be a number"}, status_code=400)
        kind = body.get("kind") or None
        if kind not in (None, "role", "founder"):
            return JSONResponse({"error": "kind must be 'role' or 'founder'"}, status_code=400)
        if lock.locked():
            return JSONResponse({"error": "a search is already running"}, status_code=409)
        async with lock:
            result = await asyncio.to_thread(
                finder.find,
                conn,
                count=count,
                kind=kind,
                force_refresh=bool(body.get("refresh")),
                hunter_api_key=settings.hunter_api_key if body.get("find_founders", True) else "",
                genai_client=llm_client,
                model=model,
                location=_location(body.get("location")),
                max_team=_int_or_none(body.get("max_team", 40)),
                min_team=_int_or_none(body.get("min_team", 10)),
                require_ai=bool(body.get("require_ai", True)),
                crustdata_api_key=settings.crustdata_api_key if body.get("enrich", True) else "",
                apollo_api_key=getattr(settings, "apollo_api_key", "") if body.get("find_founders", True) else "",
                prospeo_api_key=getattr(settings, "prospeo_api_key", "") if body.get("find_founders", True) else "",
            )
        return JSONResponse(result)

    @router.get("/leads", response_model=None)
    async def list_leads(
        token: str = "",
        status: Optional[str] = None,
        kind: Optional[str] = None,
        region: Optional[str] = None,
        min_score: float = 0,
        limit: int = 50,
    ) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        leads = await asyncio.to_thread(leads_store.list_leads, conn, status, kind, region, min_score, min(limit, 500))
        return JSONResponse({"leads": leads, "stats": await asyncio.to_thread(leads_store.stats, conn)})

    @router.get("/leads/{lead_id}", response_model=None)
    async def get_lead(lead_id: int, token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        lead = await asyncio.to_thread(leads_store.get_lead, conn, lead_id)
        if lead is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(lead)

    @router.patch("/leads/{lead_id}", response_model=None)
    async def update_lead(lead_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        status = body.get("status")
        if status not in leads_store.STATUSES:
            return JSONResponse({"error": f"status must be one of {list(leads_store.STATUSES)}"}, status_code=400)
        ok = await asyncio.to_thread(leads_store.update_status, conn, lead_id, status)
        if not ok:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(await asyncio.to_thread(leads_store.get_lead, conn, lead_id))

    @router.post("/leads/{lead_id}/draft", response_model=None)
    async def draft(lead_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        lead = await asyncio.to_thread(finder.draft_lead, conn, lead_id, llm_client, model, settings.hunter_api_key,
            getattr(settings, "crustdata_api_key", ""), getattr(settings, "apollo_api_key", ""),
            getattr(settings, "prospeo_api_key", ""),
        )
        if lead is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(lead)

    @router.post("/leads/{lead_id}/send", response_model=None)
    async def send(lead_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        lead = await asyncio.to_thread(leads_store.get_lead, conn, lead_id)
        if lead is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        raw_to = body.get("to") or lead.get("draft_to") or ""
        wanted = [e.strip() for e in (raw_to if isinstance(raw_to, list) else str(raw_to).split(",")) if e.strip()]
        wanted = list(dict.fromkeys(wanted))
        subject = (body.get("subject") or lead.get("draft_subject") or "").strip()
        text = (body.get("body") or lead.get("draft_body") or "").strip()
        if not wanted or not all(EMAIL_RE.match(e) for e in wanted):
            return JSONResponse({"error": "no valid recipient email"}, status_code=400)
        if not subject or not text:
            return JSONResponse({"error": "subject and body are required"}, status_code=400)
        already = set(leads_store.sent_recipients(lead))
        todo = [e for e in wanted if e.lower() not in already or body.get("resend")]
        if not todo:
            return JSONResponse({"error": f"already emailed {', '.join(wanted)}"}, status_code=409)
        resume = Path(settings.resume_pdf).expanduser() if settings.resume_pdf else None
        if resume is not None and not resume.is_file():
            return JSONResponse({"error": f"resume not found at {resume}"}, status_code=400)
        names = {(p.get("email") or "").lower(): p.get("name") for p in lead.get("founders") or []}
        creds = await asyncio.to_thread(google_auth.get_credentials)
        sent, failed = [], []
        for to in todo:
            personal = email_draft.for_recipient(text, names.get(to.lower()))
            result = await asyncio.to_thread(
                gmail.send_rich_email, creds, to, subject, personal,
                email_draft.to_html(personal, campaign=email_draft.utm_slug(lead["company"]),
                                    content=email_draft.utm_slug((names.get(to.lower()) or "").split(" ")[0]) or None),
                resume, email_draft.ATTACHMENT_NAME,
            )
            if result.startswith("ERROR") or result == gmail.NOT_CONNECTED:
                failed.append(f"{to}: {result}")
            else:
                sent.append(to)
        if sent:
            await asyncio.to_thread(leads_store.mark_sent, conn, lead_id, sent, subject, text)
        if failed:
            return JSONResponse({"error": "; ".join(failed), "sent": sent}, status_code=502)
        return JSONResponse(await asyncio.to_thread(leads_store.get_lead, conn, lead_id))

    return router
