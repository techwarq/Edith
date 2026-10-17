"""Autonomous job-search/apply pipeline.

Tool names deliberately use job_application/job_lead/jobs_* phrasing, never a
bare "job_*"/"list_jobs" name — edith/tools/system/scheduling.py already registers
list_jobs for Temporal schedules, and ToolRegistry rejects duplicate names.

Discovery/decision-making (which companies fit, email vs. web-form, is a
posting a good match) lives in the calling agent's own reasoning across a
sequence of tool calls (browse_url, web_search, hunter_*, this module) —
these functions are composable primitives, not a bespoke per-site scraper.

Autonomy: send_email/fill_form's pending_action + /approve gate (see
edith/integrations/google/gmail.py, edith/integrations/browse.py) is untouched for all normal chat use.
send_job_application_email/submit_job_application_form below check a
separate opt-in flag (jobs_autonomous_enabled, off by default) and either
queue through that same gate (flag off) or call the existing executors
directly (flag on) — a second, narrowly-scoped path to real sends/submits,
off until the user has reviewed a monitored test batch and turned it on.
"""

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from edith.integrations import browse
from edith.integrations.google import auth as google_auth
from edith.integrations.google import gmail as google_gmail
from edith.memory.records import system
from edith.plugins.career import store as career
from edith.tools.base import ToolContext, tool

logger = logging.getLogger("edith.tools.job_applications")

JOBS_CONFIG_CATEGORY = "jobs_config"
JOB_SOURCE_CATEGORY = "job_source"
AUTONOMOUS_KEY = "jobs_autonomous_enabled"

_SEED_JOB_SOURCES = {
    "https://jobs.a16z.com/jobs": "a16z portfolio jobs board (Consider-powered) — filter for AI Engineer / Backend / Frontend / Full-stack, remote-only, Python/Node/React/Cloud Run.",
    "https://www.ycombinator.com/jobs": "YC jobs board — filter for AI Engineer / Backend / Frontend / Full-stack, remote-only, 10-30 person early but well-funded teams.",
    "https://jobs.sequoiacap.com/jobs": "Sequoia portfolio jobs board — filter for remote AI/Backend/Frontend roles, small well-funded teams.",
    "https://www.accel.com/jobs": "Accel portfolio jobs — filter for remote AI/Backend/Frontend roles.",
    "https://jobs.lightspeedvp.com/jobs": "Lightspeed portfolio jobs board — filter for remote AI/Backend/Frontend roles.",
    "https://jobs.greylock.com/jobs": "Greylock portfolio jobs board — filter for remote AI/Backend/Frontend roles.",
    "https://jobs.firstround.com/jobs": "First Round portfolio jobs — early-stage 10-30 person teams, remote-friendly.",
    "https://jobs.500.co/jobs": "500 Global portfolio jobs — early-stage remote roles.",
    "https://jobs.techstars.com/jobs": "Techstars portfolio jobs — early-stage remote roles.",
    "https://www.workatastartup.com/jobs": "YC Work at a Startup — directly filter remote + AI Engineer/Backend/Frontend.",
}

_FALLBACK_STYLE_INSTRUCTION = (
    "No writing-style sample is available yet, so write in a professional-but-personal "
    "tone inferred from the resume content itself: direct, technical, no corporate "
    "boilerplate. (Tell the user to paste sample emails into email.txt and re-run "
    "scripts/ingest_resume.py for better voice-matching.)"
)


def _normalize_domain(url_or_domain: str) -> Optional[str]:
    s = (url_or_domain or "").strip().lower()
    if not s:
        return None
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/")[0]
    if s.startswith("www."):
        s = s[4:]
    return s or None


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unknown"


def _dedup_key(company: str, company_domain: str = "", *urls: str) -> str:
    for candidate in (company_domain, *urls):
        domain = _normalize_domain(candidate)
        if domain:
            return domain
    return _slugify(company)


def _parse_json_object(text: str) -> Optional[dict[str, Any]]:
    cleaned = (text or "").strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def seed_job_sources(conn: sqlite3.Connection) -> None:
    if not system.list_settings(conn, JOB_SOURCE_CATEGORY):
        for url, note in _SEED_JOB_SOURCES.items():
            system.set_setting(conn, key=url, value=note, category=JOB_SOURCE_CATEGORY)


@tool
def record_job_lead(
    ctx: ToolContext,
    company: str,
    role_title: str = "",
    source: str = "",
    source_url: str = "",
    job_posting_url: str = "",
    company_domain: str = "",
) -> str:
    """Record a candidate company/role as a job-application lead, after checking it's
    not a duplicate. Use once you've identified a company worth applying to from a
    job source (browse_url on a VC portfolio jobs page, etc).

    Args:
        source: e.g. 'a16z', 'ycombinator', 'web_search'
        source_url: The listing/portfolio page this lead came from.
        job_posting_url: The specific job posting/apply page, if found.
        company_domain: Company's domain, if known (e.g. 'acme.com') — used for dedup.
    """
    domain = _dedup_key(company, company_domain, job_posting_url, source_url)
    existing = career.find_existing_application(ctx.conn, domain)
    if existing:
        return f"Already tracked as #{existing['id']} ({existing['status']}) — skipping duplicate."
    app_id = career.create_application(
        ctx.conn,
        company=company,
        company_domain=domain,
        role_title=role_title or None,
        source=source or None,
        source_url=source_url or None,
        job_posting_url=job_posting_url or None,
    )
    return f"Recorded lead #{app_id}: {company} — {role_title or '(no specific role)'}"


@tool
def check_company_applied(ctx: ToolContext, company: str, company_domain: str = "") -> str:
    """Check whether there's already an in-flight or completed application for a company, before doing further work on it."""
    domain = _dedup_key(company, company_domain)
    existing = career.find_existing_application(ctx.conn, domain)
    if existing:
        return f"Already in flight: #{existing['id']} ({existing['status']}) — skip {company}."
    return f"No existing in-flight application for {company} — safe to proceed."


@tool
def draft_job_application(ctx: ToolContext, application_id: int, job_posting_text: str) -> str:
    """Write a tailored application (resume framing + email subject/body) for a recorded
    lead, grounded strictly in the user's ingested resume text and their writing-style
    sample if available. Persists the draft on the application row.

    Args:
        job_posting_text: The job posting/page content (e.g. browse_url's output) to tailor against.
    """
    conn = ctx.conn
    app = career.get_application(conn, application_id)
    if app is None:
        return f"ERROR: no application #{application_id}."

    resume_text = career.get_resume_text(conn)
    if not resume_text:
        return "ERROR: no resume ingested yet — run scripts/ingest_resume.py before drafting."

    style_sample = career.get_style_sample(conn)
    style_instruction = (
        f"Match this writing voice/style, drawn from the user's own past emails:\n{style_sample}"
        if style_sample
        else _FALLBACK_STYLE_INSTRUCTION
    )

    prompt = (
        "Draft a job application for the user based on their resume below. Ground every claim "
        "ONLY in what's literally in the resume text — never invent metrics, employers, titles, "
        "or experience not present there. It's fine to omit or generalize, never fabricate.\n\n"
        f"Company: {app['company']}\nRole: {app['role_title'] or '(unspecified)'}\n\n"
        f"Resume:\n{resume_text}\n\n"
        f"{style_instruction}\n\n"
        f"Job posting / page content:\n{job_posting_text[:4000]}\n\n"
        "Reply with ONLY a JSON object, no other text: "
        '{"resume_summary": "2-3 sentence tailored framing of the resume for this role", '
        '"subject": "email subject line", "body": "full email/cover-letter body, first person, '
        'ready to send as-is"}'
    )
    resp = ctx.genai_client.models.generate_content(model=ctx.genai_model, contents=prompt)
    parsed = _parse_json_object(resp.text or "")
    if not parsed or not parsed.get("body"):
        return "ERROR: could not parse a draft from the model — try again."

    career.update_application(
        conn,
        application_id,
        status="drafted",
        draft_subject=str(parsed.get("subject") or f"Application: {app['role_title'] or app['company']}"),
        draft_body=str(parsed["body"]),
        resume_summary=str(parsed.get("resume_summary") or ""),
    )
    note = "" if style_sample else "\n\n(Note: drafted with a fallback tone — no writing-style sample ingested yet.)"
    return f"Drafted application #{application_id} for {app['company']}.{note}"


@tool
def set_application_channel(ctx: ToolContext, application_id: int, channel: Literal["email", "web_form"]) -> str:
    """Set whether an application will be applied to via 'email' or 'web_form'."""
    if channel not in ("email", "web_form"):
        return "ERROR: channel must be 'email' or 'web_form'."
    if not career.update_application(ctx.conn, application_id, channel=channel):
        return f"ERROR: no application #{application_id}."
    return f"Set application #{application_id} channel to {channel}."


@tool
def list_job_applications(ctx: ToolContext, status: str = "") -> str:
    """List tracked job applications, optionally filtered by status (discovered/drafted/queued_for_approval/sent/applied/failed/skipped_duplicate)."""
    apps = career.list_applications(ctx.conn, status=status or None)
    if not apps:
        return "No job applications tracked yet."
    return "\n".join(
        f"#{a['id']} {a['company']} — {a['role_title'] or '(no role)'} "
        f"[{a['channel']}] status={a['status']}"
        for a in apps
    )


@tool
def enable_jobs_autonomous_mode(ctx: ToolContext) -> str:
    """Turn on autonomous sending/submitting for the job-application pipeline — after this,
    send_job_application_email/submit_job_application_form send/submit directly instead of
    queuing for /approve. Only call this after the user has explicitly reviewed a monitored
    test batch and told you to turn it on.
    """
    system.set_setting(ctx.conn, key=AUTONOMOUS_KEY, value="true", category=JOBS_CONFIG_CATEGORY)
    return (
        "Autonomous mode ENABLED — send_job_application_email/submit_job_application_form "
        "will now send/submit directly, without queuing for /approve."
    )


@tool
def disable_jobs_autonomous_mode(ctx: ToolContext) -> str:
    """Turn off autonomous sending — future sends/submits go back through the /approve gate."""
    system.set_setting(ctx.conn, key=AUTONOMOUS_KEY, value="false", category=JOBS_CONFIG_CATEGORY)
    return "Autonomous mode DISABLED — sends/submits will queue for /approve again."


def _is_autonomous(conn: sqlite3.Connection) -> bool:
    return system.get_setting(conn, AUTONOMOUS_KEY) == "true"


@tool
def send_job_application_email(ctx: ToolContext, application_id: int, to: str, subject: str, body: str) -> str:
    """Send (or, if autonomous mode is off, queue for /approve) the application email for a
    drafted lead. Call draft_job_application first.
    """
    conn = ctx.conn
    app = career.get_application(conn, application_id)
    if app is None:
        return f"ERROR: no application #{application_id}."

    if not _is_autonomous(conn):
        action_id = system.queue_pending_action(
            conn,
            tool_name="send_email",
            args={"to": to, "subject": subject, "body": body},
            preview=f"[Job application to {app['company']}] Send email to {to}\nSubject: {subject}\n\n{body}",
        )
        career.update_application(
            conn, application_id, status="queued_for_approval", pending_action_id=action_id,
            contact_email=to, draft_subject=subject, draft_body=body,
        )
        return f"Queued as action #{action_id} — autonomous mode is off, run /approve to send."

    creds = google_auth.get_credentials()
    result = google_gmail.execute_send_email(creds, {"to": to, "subject": subject, "body": body})
    ok = not result.startswith("ERROR")
    career.update_application(
        conn, application_id,
        status="sent" if ok else "failed",
        contact_email=to, draft_subject=subject, draft_body=body,
        sent_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ") if ok else None,
        error=None if ok else result,
    )
    return result


@tool
def submit_job_application_form(ctx: ToolContext, application_id: int, url: str, field_values: dict[str, str]) -> str:
    """Submit (or, if autonomous mode is off, queue for /approve) a web application form for
    a lead. Call browse_url on the apply page first to see its fields.

    Args:
        field_values: Map of form field name -> value.
    """
    conn = ctx.conn
    app = career.get_application(conn, application_id)
    if app is None:
        return f"ERROR: no application #{application_id}."

    if not _is_autonomous(conn):
        preview_lines = "\n".join(f"{name} = {value}" for name, value in field_values.items())
        action_id = system.queue_pending_action(
            conn,
            tool_name="submit_form",
            args={"url": url, "field_values": field_values},
            preview=f"[Job application to {app['company']}] Submit form at {url}\n\n{preview_lines}",
        )
        career.update_application(
            conn, application_id, status="queued_for_approval", pending_action_id=action_id,
            job_posting_url=url,
        )
        return f"Queued as action #{action_id} — autonomous mode is off, run /approve to submit."

    result = browse.execute_submit_form(None, {"url": url, "field_values": field_values})
    ok = not result.startswith("ERROR")
    career.update_application(
        conn, application_id,
        status="applied" if ok else "failed",
        job_posting_url=url,
        sent_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ") if ok else None,
        error=None if ok else result,
    )
    return result


@tool
def track_job_source(ctx: ToolContext, url: str, note: str = "") -> str:
    """Add a URL (VC portfolio jobs board, etc) to the list of sources the job-search pipeline scans."""
    system.set_setting(ctx.conn, key=url, value=note or url, category=JOB_SOURCE_CATEGORY)
    return f"Now tracking {url} as a job source."


@tool
def untrack_job_source(ctx: ToolContext, url: str) -> str:
    """Stop scanning a previously tracked job source URL."""
    removed = system.delete_setting(ctx.conn, url)
    return f"Stopped tracking {url}." if removed else f"{url} wasn't tracked."


@tool
def list_job_sources(ctx: ToolContext) -> str:
    """List every job-source URL the pipeline currently scans."""
    facts = system.list_settings(ctx.conn, JOB_SOURCE_CATEGORY)
    if not facts:
        return "No job sources tracked yet."
    return "\n".join(f"{f['key']} — {f['value']}" for f in facts)
