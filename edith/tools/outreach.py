"""Semi-auto founder/hiring-manager outreach: LinkedIn DMs + cold email.

Design: Edith finds prospects from VC portfolio team pages / Work at a Startup /
web_search / monid, resolves email via hunter_*, drafts hyper-personalized copy
grounded in Sonali's resume — but NEVER sends LinkedIn DMs itself (ToS/ban risk).
User sends from their own LinkedIn; Edith tracks queued -> contacted -> replied.

Tools:
- add_outreach_prospect: deduped insert, returns LinkedIn URL for 1-click send.
- list_outreach_prospects: what to send today.
- draft_outreach_message: kind=linkedin_dm (<250 chars) or cold_email (subject+body).
- mark_prospect_contacted: update status after user sends.
"""

import json
import logging
import sqlite3

from google import genai

from edith.memory import job_applications_store as jobs_store
from edith.memory import outreach_store as prospects
from edith.tools.registry import ToolRegistry

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


def register(registry: ToolRegistry, conn: sqlite3.Connection, genai_client: genai.Client, model: str) -> None:
    def add_outreach_prospect(
        name: str,
        linkedin_url: str = "",
        company: str = "",
        company_domain: str = "",
        role: str = "",
        contact_email: str = "",
        context: str = "",
    ) -> str:
        if not name:
            return "ERROR: name is required."
        existing = prospects.find_existing_prospect(conn, linkedin_url, contact_email, company_domain)
        if existing:
            return f"Already tracked as prospect #{existing['id']} ({existing['status']}) — skipping duplicate."
        pid = prospects.create_prospect(
            conn, name=name, linkedin_url=linkedin_url or None,
            company=company or None, company_domain=company_domain or None,
            role=role or None, contact_email=contact_email or None,
            context=context or None,
        )
        link = f" — {linkedin_url}" if linkedin_url else ""
        return f"Queued prospect #{pid}: {name} ({role or 'unknown role'} at {company or 'unknown'}){link}"

    def list_outreach_prospects(status: str = "") -> str:
        rows = prospects.list_prospects(conn, status=status or None)
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

    def draft_outreach_message(prospect_id: int, kind: str = "linkedin_dm", extra_context: str = "") -> str:
        if kind not in ("linkedin_dm", "cold_email"):
            return "ERROR: kind must be 'linkedin_dm' or 'cold_email'."
        p = prospects.get_prospect(conn, prospect_id)
        if p is None:
            return f"ERROR: no prospect #{prospect_id}."
        resume_text = jobs_store.get_resume_text(conn)
        if not resume_text:
            return "ERROR: no resume ingested yet — run scripts/ingest_resume.py before drafting."

        if kind == "linkedin_dm":
            fmt = (
                'Reply with ONLY a JSON object: {"dm": "connection note or DM, max 250 chars, '
                'first person, reference their product + one concrete Sonali proof point"}.'
            )
        else:
            fmt = (
                'Reply with ONLY a JSON object: {"subject": "email subject", '
                '"body": "full cold email body, first person, ready to send as-is"}.'
            )
        prompt = (
            "Draft founder/hiring-manager outreach for Sonali Nayak (Full Stack / AI Engineer: "
            "Python, Node.js, JavaScript, React.js, Next.js, TypeScript, Cloud Run/GCP, Redis, "
            "BullMQ, RAG, LLM APIs, multi-agent platforms at Nagent AI). Ground every claim ONLY "
            "in the resume — never invent metrics or employers.\n\n"
            f"Prospect: {p['name']} — {p['role'] or '?'} at {p['company'] or '?'} "
            f"({p['company_domain'] or 'no domain'})\n"
            f"LinkedIn: {p['linkedin_url'] or 'unknown'}\n"
            f"Context: {p['context'] or ''}\nExtra: {extra_context[:1000]}\n\n"
            f"Resume:\n{resume_text[:4000]}\n\n{fmt}"
        )
        resp = genai_client.models.generate_content(model=model, contents=prompt)
        parsed = _parse_json_object(resp.text or "")
        if not parsed:
            return "ERROR: could not parse a draft from the model — try again."
        if kind == "linkedin_dm":
            dm = str(parsed.get("dm") or "").strip()
            if not dm:
                return "ERROR: model returned empty DM — try again."
            prospects.update_prospect(conn, prospect_id, dm_draft=dm)
            return f"Drafted LinkedIn DM for prospect #{prospect_id} ({len(dm)} chars):\n\n{dm}\n\nSend from your LinkedIn: {p['linkedin_url'] or '(no URL saved)'}"
        subject = str(parsed.get("subject") or f"Quick intro — Full Stack / AI Engineer (React + Node + RAG)")
        body = str(parsed.get("body") or "")
        if not body:
            return "ERROR: model returned empty email body — try again."
        prospects.update_prospect(conn, prospect_id, email_draft_subject=subject, email_draft_body=body)
        return f"Drafted cold email for prospect #{prospect_id}.\nSubject: {subject}\n\n{body}"

    def mark_prospect_contacted(prospect_id: int, status: str = "contacted") -> str:
        if status not in ("contacted", "replied", "skipped", "queued"):
            return "ERROR: status must be one of contacted, replied, skipped, queued."
        if not prospects.update_prospect(conn, prospect_id, status=status):
            return f"ERROR: no prospect #{prospect_id}."
        return f"Prospect #{prospect_id} marked {status}."

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "add_outreach_prospect",
                "description": (
                    "Queue a founder/hiring-manager for semi-auto outreach (LinkedIn + cold email). "
                    "Dedupes by LinkedIn URL/email/domain. Always capture linkedin_url when you can find "
                    "it (company team page, web_search, monid) so the user can 1-click send."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "linkedin_url": {"type": "string"},
                        "company": {"type": "string"},
                        "company_domain": {"type": "string"},
                        "role": {"type": "string", "description": "e.g. Founder, CTO, Hiring Manager"},
                        "contact_email": {"type": "string"},
                        "context": {"type": "string", "description": "Why this person: product note, JD link, funding signal."},
                    },
                    "required": ["name"],
                },
            },
        },
        add_outreach_prospect,
    )
    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_outreach_prospects",
                "description": "List queued/contacted outreach prospects with their LinkedIn URLs for 1-click sending.",
                "parameters": {"type": "object", "properties": {"status": {"type": "string"}}},
            },
        },
        list_outreach_prospects,
    )
    registry.register(
        {
            "type": "function",
            "function": {
                "name": "draft_outreach_message",
                "description": (
                    "Draft a hyper-personalized LinkedIn DM (<250 chars) or cold email for a prospect, "
                    "grounded strictly in the ingested resume. LinkedIn DMs are never auto-sent — "
                    "the user sends them manually."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prospect_id": {"type": "integer"},
                        "kind": {"type": "string", "enum": ["linkedin_dm", "cold_email"]},
                        "extra_context": {"type": "string"},
                    },
                    "required": ["prospect_id"],
                },
            },
        },
        draft_outreach_message,
    )
    registry.register(
        {
            "type": "function",
            "function": {
                "name": "mark_prospect_contacted",
                "description": "Mark a prospect contacted/replied/skipped after the user sends (or skips) the DM/email.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prospect_id": {"type": "integer"},
                        "status": {"type": "string", "enum": ["contacted", "replied", "skipped", "queued"]},
                    },
                    "required": ["prospect_id", "status"],
                },
            },
        },
        mark_prospect_contacted,
    )
