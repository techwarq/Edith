"""Semi-auto founder/hiring-manager outreach: LinkedIn DMs + cold email.

Design: Edith finds prospects from VC portfolio team pages / Work at a Startup /
web_search / monid, resolves email via hunter_*, drafts hyper-personalized copy
grounded in the user's resume (and career profile) — but NEVER sends LinkedIn DMs itself (ToS/ban risk).
User sends from their own LinkedIn; Edith tracks queued -> contacted -> replied.

Tools:
- add_outreach_prospect: deduped insert, returns LinkedIn URL for 1-click send.
- list_outreach_prospects: what to send today.
- draft_outreach_message: kind=linkedin_dm (<250 chars) or cold_email (subject+body).
- mark_prospect_contacted: update status after user sends.
"""

import json
import logging
from typing import Literal

from edith.plugins.career import profile
from edith.plugins.career import store as career
from edith.tools.base import ToolContext, tool

logger = logging.getLogger("edith.tools.outreach")


def _parse_json_object(text: str):
    cleaned = (text or "").strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


@tool
def add_outreach_prospect(
    ctx: ToolContext,
    name: str,
    linkedin_url: str = "",
    company: str = "",
    company_domain: str = "",
    role: str = "",
    contact_email: str = "",
    context: str = "",
) -> str:
    """Queue a founder/hiring-manager for semi-auto outreach (LinkedIn + cold email).
    Dedupes by LinkedIn URL/email/domain. Always capture linkedin_url when you can find
    it (company team page, web_search, monid) so the user can 1-click send.

    Args:
        role: e.g. Founder, CTO, Hiring Manager
        context: Why this person: product note, JD link, funding signal.
    """
    if not name:
        return "ERROR: name is required."
    existing = career.find_existing_prospect(ctx.conn, linkedin_url, contact_email, company_domain)
    if existing:
        return f"Already tracked as prospect #{existing['id']} ({existing['status']}) — skipping duplicate."
    pid = career.create_prospect(
        ctx.conn, name=name, linkedin_url=linkedin_url or None,
        company=company or None, company_domain=company_domain or None,
        role=role or None, contact_email=contact_email or None,
        context=context or None,
    )
    link = f" — {linkedin_url}" if linkedin_url else ""
    return f"Queued prospect #{pid}: {name} ({role or 'unknown role'} at {company or 'unknown'}){link}"


@tool
def list_outreach_prospects(ctx: ToolContext, status: str = "") -> str:
    """List queued/contacted outreach prospects with their LinkedIn URLs for 1-click sending."""
    rows = career.list_prospects(ctx.conn, status=status or None)
    if not rows:
        return "No outreach prospects tracked yet."
    lines = []
    for p in rows:
        link = p["linkedin_url"] or "no-linkedin-url"
        lines.append(
            f"#{p['id']} {p['name']} — {p['role'] or '?'} at {p['company'] or '?'} "
            f"[{p['status']}] {link}"
        )
    return "\n".join(lines)


@tool
def draft_outreach_message(
    ctx: ToolContext,
    prospect_id: int,
    kind: Literal["linkedin_dm", "cold_email"] = "linkedin_dm",
    extra_context: str = "",
) -> str:
    """Draft a hyper-personalized LinkedIn DM (<250 chars) or cold email for a prospect,
    grounded strictly in the ingested resume. LinkedIn DMs are never auto-sent —
    the user sends them manually.
    """
    if kind not in ("linkedin_dm", "cold_email"):
        return "ERROR: kind must be 'linkedin_dm' or 'cold_email'."
    p = career.get_prospect(ctx.conn, prospect_id)
    if p is None:
        return f"ERROR: no prospect #{prospect_id}."
    resume_text = career.get_resume_text(ctx.conn)
    if not resume_text:
        return "ERROR: no resume ingested yet — run scripts/ingest_resume.py before drafting."
    me = profile.load()

    if kind == "linkedin_dm":
        fmt = (
            'Reply with ONLY a JSON object: {"dm": "connection note or DM, max 250 chars, '
            'first person, reference their product + one concrete proof point from the resume"}.'
        )
    else:
        fmt = (
            'Reply with ONLY a JSON object: {"subject": "email subject", '
            '"body": "full cold email body, first person, ready to send as-is"}.'
        )
    prompt = (
        f"Draft founder/hiring-manager outreach for {me.get('name', 'the user')} "
        f"({me.get('headline', '')}: {me.get('stack', '')}). Ground every claim ONLY "
        "in the resume — never invent metrics or employers.\n\n"
        f"Prospect: {p['name']} — {p['role'] or '?'} at {p['company'] or '?'} "
        f"({p['company_domain'] or 'no domain'})\n"
        f"LinkedIn: {p['linkedin_url'] or 'unknown'}\n"
        f"Context: {p['context'] or ''}\nExtra: {extra_context[:1000]}\n\n"
        f"Resume:\n{resume_text[:4000]}\n\n{fmt}"
    )
    resp = ctx.genai_client.models.generate_content(model=ctx.genai_model, contents=prompt)
    parsed = _parse_json_object(resp.text or "")
    if not parsed:
        return "ERROR: could not parse a draft from the model — try again."
    if kind == "linkedin_dm":
        dm = str(parsed.get("dm") or "").strip()
        if not dm:
            return "ERROR: model returned empty DM — try again."
        career.update_prospect(ctx.conn, prospect_id, dm_draft=dm)
        return f"Drafted LinkedIn DM for prospect #{prospect_id} ({len(dm)} chars):\n\n{dm}\n\nSend from your LinkedIn: {p['linkedin_url'] or '(no URL saved)'}"
    subject = str(parsed.get("subject") or f"Quick intro — Full Stack / AI Engineer (React + Node + RAG)")
    body = str(parsed.get("body") or "")
    if not body:
        return "ERROR: model returned empty email body — try again."
    career.update_prospect(ctx.conn, prospect_id, email_draft_subject=subject, email_draft_body=body)
    return f"Drafted cold email for prospect #{prospect_id}.\nSubject: {subject}\n\n{body}"


@tool
def mark_prospect_contacted(
    ctx: ToolContext, prospect_id: int, status: Literal["contacted", "replied", "skipped", "queued"]
) -> str:
    """Mark a prospect contacted/replied/skipped after the user sends (or skips) the DM/email."""
    if status not in ("contacted", "replied", "skipped", "queued"):
        return "ERROR: status must be one of contacted, replied, skipped, queued."
    if not career.update_prospect(ctx.conn, prospect_id, status=status):
        return f"ERROR: no prospect #{prospect_id}."
    return f"Prospect #{prospect_id} marked {status}."
