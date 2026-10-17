"""enable_jobs_pipeline / disable_jobs_pipeline — the recurring job-search run, an
ordinary fixed-instruction Temporal schedule whose instruction is built from the
career profile's `jobs` section."""

import asyncio

from edith.config import JOB_SEARCH_CRON, JOB_SEARCH_LEADS_PER_RUN, JOB_SEARCH_SCHEDULE_ID, JOBS_DAILY_CAP
from edith.plugins.career import profile
from edith.temporal import schedules
from edith.temporal.client import TemporalNotConfigured, get_client
from edith.tools.base import ToolContext, tool


def job_search_instruction(leads_per_run: int) -> str:
    me = profile.require()
    jobs = me.get("jobs") or {}
    return f"""\
This is a scheduled job-application run — nobody is watching live except possibly during the
first monitored test batch (autonomous mode may still be off, in which case sends/submits will
queue for /approve instead of going out directly — that's expected and correct).

USER PROFILE: {me.get("name", "the user")}, {me.get("headline", "")}. Stack: {me.get("stack", "")}.
Target roles: {jobs.get("target_roles", "")}.
{jobs.get("preferences", "")}

1. Call list_job_applications status="sent" and also status="applied", and count how many have
   a sent_at from today. If that count is already at or above {JOBS_DAILY_CAP}, stop here and
   say so briefly — don't discover or draft anything else this run.
2. Call list_job_sources for the VC portfolio/jobs-board pages to scan. Occasionally (not every
   run) also run web_search for 1-2 more VC/accelerator portfolio jobs boards (e.g. "<firm> jobs
   board" — many are Consider/Getro-powered pages like jobs.a16z.com, jobs.sequoiacap.com,
   which browse_url renders fine) and track_job_source anything promising.
3. For each source, browse_url it. From the page text, identify companies/roles matching the
   target roles, stack, and preferences above. Read each listing's location text carefully.
   For each candidate, call check_company_applied first and skip anything already in flight,
   then record_job_lead for genuinely new ones.
4. For up to {leads_per_run} of today's newly recorded leads: find a contact email via
   hunter_domain_search/hunter_email_finder + hunter_email_verifier if the posting's primary CTA
   isn't a dedicated apply form; otherwise the channel is web_form (browse_url the apply page to
   see its fields first). ALSO capture the founder/hiring-manager for LinkedIn semi-auto outreach:
   call add_outreach_prospect with name, linkedin_url (from web_search/monid or company team page),
   company, role, and context. Draft a short personalized LinkedIn connect note via
   draft_outreach_message (kind="linkedin_dm", <250 chars, {jobs.get("outreach_hook", "reference their product")}).
   Draft the email via draft_job_application, then send_job_application_email or
   submit_job_application_form.
5. Keep your final reply a short summary of what happened this run (companies, channel, status,
   + LinkedIn prospects queued) — it's read later via the Jobs tab/`/jobs`, not this chat.
"""


@tool
def enable_jobs_pipeline(ctx: ToolContext) -> str:
    """Turn on the autonomous job-application pipeline: several times a day it scans
    tracked VC/accelerator job sources, records/drafts/applies to new leads matching the
    career profile's target roles up to the daily cap, plus queues LinkedIn semi-auto
    prospects. Off by default — only enable after the user has reviewed a monitored test
    batch (via schedule_once).
    """
    try:
        instruction = job_search_instruction(JOB_SEARCH_LEADS_PER_RUN)

        async def _do() -> None:
            client = await get_client(ctx.settings)
            await schedules.ensure_instruction_schedule(client, JOB_SEARCH_SCHEDULE_ID, instruction, JOB_SEARCH_CRON)

        asyncio.run(_do())
    except (TemporalNotConfigured, profile.ProfileMissing) as e:
        return f"ERROR: {e}"
    return (
        f"Job-search pipeline enabled (cron: {JOB_SEARCH_CRON}, ~{JOB_SEARCH_LEADS_PER_RUN} leads/run). "
        "A Temporal worker process must be running for it to actually fire. If jobs_autonomous_enabled "
        "is off, sends/submits will queue for /approve instead of going out directly."
    )


@tool
def disable_jobs_pipeline(ctx: ToolContext) -> str:
    """Turn off the recurring job-application pipeline."""
    async def _do() -> bool:
        client = await get_client(ctx.settings)
        return await schedules.cancel_schedule(client, JOB_SEARCH_SCHEDULE_ID)

    try:
        disabled = asyncio.run(_do())
    except TemporalNotConfigured as e:
        return f"ERROR: {e}"
    return "Job-search pipeline disabled." if disabled else "Job-search pipeline wasn't enabled."
