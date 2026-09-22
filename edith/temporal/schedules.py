"""Temporal Schedule helpers — thin wrappers so the schedule_job tool and the
nightly reflection setup don't touch the Temporal SDK's Schedule API directly.
Every schedule triggers the same RunAgentInstructionWorkflow with a fixed
instruction string baked in at creation time.
"""

import uuid
from datetime import datetime, timedelta, timezone

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleHandle,
    ScheduleSpec,
    WorkflowHandle,
)
from temporalio.service import RPCError, RPCStatusCode

from edith.config import (
    JOB_SEARCH_CRON,
    JOB_SEARCH_SCHEDULE_ID,
    JOBS_DAILY_CAP,
    NIGHTLY_EVALS_CRON,
    NIGHTLY_EVALS_SCHEDULE_ID,
    NIGHTLY_REFLECTION_CRON,
    NIGHTLY_REFLECTION_SCHEDULE_ID,
    TEMPORAL_TASK_QUEUE,
)
from edith.temporal.workflows import DeepResearchWorkflow, RunAgentInstructionWorkflow, RunEvalsWorkflow

JOB_SCHEDULE_PREFIX = "edith-job-"
ONCE_WORKFLOW_PREFIX = "edith-once-"
DEEP_RESEARCH_WORKFLOW_PREFIX = "edith-deep-research-"

NIGHTLY_REFLECTION_INSTRUCTION = """\
This is your nightly reflection run — nobody is watching this live, so write for later reading, not conversation.

1. Call list_tracked_urls. For each URL returned, call browse_url and look for anything
   genuinely new or notable since you'd have last seen it.
2. Cross-reference what you find against the facts/goals/projects you already know about me
   (they're in your system prompt) — I only care about news that's actually relevant to me,
   not a generic roundup.
3. For anything durable worth remembering long-term (a pattern, a shift in something I track),
   call save_fact. Don't save one-off transient details.
4. Write a concise digest: what's relevant and why, plus concrete ideas or next steps it
   suggests for me. If nothing relevant turned up, say so briefly rather than padding it out.

Your final reply IS the digest — it gets saved for me to read later, so make it self-contained
and skip pleasantries/greetings.
"""


def _job_search_instruction(leads_per_run: int) -> str:
    return f"""\
This is a scheduled job-application run — nobody is watching live except possibly during the
first monitored test batch (autonomous mode may still be off, in which case sends/submits will
queue for /approve instead of going out directly — that's expected and correct).

USER PROFILE: Sonali Nayak, Full Stack / AI Engineer. Stack: Python, Node.js, JavaScript,
React.js, Next.js, TypeScript, Cloud Run (GCP), Redis, BullMQ, Postgres, MongoDB, RAG, LLM APIs,
Vector DBs. Target roles: AI Engineer, Backend Engineer, Frontend Engineer, Full-stack Engineer.
REMOTE-ONLY — skip any on-site/hybrid or location-locked roles unless explicitly remote-worldwide
or remote-India. Prefer 10-30 person early but well-funded startup teams (VC-backed).

1. Call list_job_applications status="sent" and also status="applied", and count how many have
   a sent_at from today. If that count is already at or above {JOBS_DAILY_CAP}, stop here and
   say so briefly — don't discover or draft anything else this run.
2. Call list_job_sources for the VC portfolio/jobs-board pages to scan. Occasionally (not every
   run) also run web_search for 1-2 more VC/accelerator portfolio jobs boards (e.g. "<firm> jobs
   board" — many are Consider/Getro-powered pages like jobs.a16z.com, jobs.sequoiacap.com,
   which browse_url renders fine) and track_job_source anything promising. Cover: a16z, YC,
   Sequoia, Accel, Lightspeed, Greylock, First Round, 500 Global, Techstars, Work at a Startup.
3. For each source, browse_url it. From the page text, identify companies/roles matching:
   AI Engineer / Backend / Frontend / Full-stack with Python/Node/React/Cloud Run keywords,
   REMOTE-ONLY. Read each listing's location text carefully — skip non-remote. Prefer small
   teams (hunter_company_enrichment to check ~10-30 employees + funded). For each candidate,
   call check_company_applied first and skip anything already in flight, then record_job_lead
   for genuinely new ones.
4. For up to {leads_per_run} of today's newly recorded leads: find a contact email via
   hunter_domain_search/hunter_email_finder + hunter_email_verifier if the posting's primary CTA
   isn't a dedicated apply form; otherwise the channel is web_form (browse_url the apply page to
   see its fields first). ALSO capture the founder/hiring-manager for LinkedIn semi-auto outreach:
   call add_outreach_prospect with name, linkedin_url (from web_search/monid or company team page),
   company, role, and context. Draft a short personalized LinkedIn connect note via
   draft_outreach_message (kind="linkedin_dm", <250 chars, reference their product + Sonali's
   Nagent AI / RAG / MCP work). Draft the email via draft_job_application, then
   send_job_application_email or submit_job_application_form.
5. Keep your final reply a short summary of what happened this run (companies, channel, status,
   + LinkedIn prospects queued) — it's read later via the Jobs tab/`/jobs`, not this chat.
"""


def _schedule_id(job_id: str) -> str:
    return f"{JOB_SCHEDULE_PREFIX}{job_id}"


async def _schedule_exists(client: Client, schedule_id: str) -> bool:
    try:
        await client.get_schedule_handle(schedule_id).describe()
        return True
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        raise


async def ensure_nightly_reflection_schedule(client: Client) -> None:
    """Idempotent. Opt-in — called from the enable_nightly_reflection tool, not
    automatically on worker startup, so turning it off actually stays off."""
    if await _schedule_exists(client, NIGHTLY_REFLECTION_SCHEDULE_ID):
        return
    await client.create_schedule(
        NIGHTLY_REFLECTION_SCHEDULE_ID,
        Schedule(
            action=ScheduleActionStartWorkflow(
                RunAgentInstructionWorkflow.run,
                NIGHTLY_REFLECTION_INSTRUCTION,
                id=f"{NIGHTLY_REFLECTION_SCHEDULE_ID}-run",
                task_queue=TEMPORAL_TASK_QUEUE,
            ),
            spec=ScheduleSpec(cron_expressions=[NIGHTLY_REFLECTION_CRON]),
        ),
    )


async def ensure_nightly_evals_schedule(client: Client) -> None:
    """Idempotent, and unlike ensure_nightly_reflection_schedule this one is
    called unconditionally on worker startup (see worker.py) — this is a
    system health check, not Edith autonomously acting on your behalf, and
    without a fixed cadence there's no time series to read "better or worse"
    off of."""
    if await _schedule_exists(client, NIGHTLY_EVALS_SCHEDULE_ID):
        return
    await client.create_schedule(
        NIGHTLY_EVALS_SCHEDULE_ID,
        Schedule(
            action=ScheduleActionStartWorkflow(
                RunEvalsWorkflow.run,
                id=f"{NIGHTLY_EVALS_SCHEDULE_ID}-run",
                task_queue=TEMPORAL_TASK_QUEUE,
            ),
            spec=ScheduleSpec(cron_expressions=[NIGHTLY_EVALS_CRON]),
        ),
    )


async def cancel_nightly_reflection(client: Client) -> bool:
    if not await _schedule_exists(client, NIGHTLY_REFLECTION_SCHEDULE_ID):
        return False
    await client.get_schedule_handle(NIGHTLY_REFLECTION_SCHEDULE_ID).delete()
    return True


async def ensure_job_search_schedule(client: Client, cron: str = JOB_SEARCH_CRON, leads_per_run: int = 3) -> None:
    """Idempotent, opt-in (see enable_jobs_pipeline) — same reasoning as
    ensure_nightly_reflection_schedule. Fires several times across the day
    (default cron) rather than once, so sends trickle instead of bursting."""
    if await _schedule_exists(client, JOB_SEARCH_SCHEDULE_ID):
        return
    await client.create_schedule(
        JOB_SEARCH_SCHEDULE_ID,
        Schedule(
            action=ScheduleActionStartWorkflow(
                RunAgentInstructionWorkflow.run,
                _job_search_instruction(leads_per_run),
                id=f"{JOB_SEARCH_SCHEDULE_ID}-run",
                task_queue=TEMPORAL_TASK_QUEUE,
            ),
            spec=ScheduleSpec(cron_expressions=[cron]),
        ),
    )


async def cancel_job_search_schedule(client: Client) -> bool:
    if not await _schedule_exists(client, JOB_SEARCH_SCHEDULE_ID):
        return False
    await client.get_schedule_handle(JOB_SEARCH_SCHEDULE_ID).delete()
    return True


async def create_job_schedule(
    client: Client, job_id: str, instruction: str, cron: str, end_at: datetime | None = None
) -> ScheduleHandle:
    """end_at uses Temporal's native ScheduleSpec.end_at so a bounded recurring
    job (e.g. "daily for a week") terminates on its own — no separate
    companion cancel_job call needed, and nothing keeps firing if that call
    were forgotten."""
    schedule_id = _schedule_id(job_id)
    if await _schedule_exists(client, schedule_id):
        raise ValueError(f"A job named '{job_id}' already exists — cancel_job it first or pick a different name.")
    return await client.create_schedule(
        schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                RunAgentInstructionWorkflow.run,
                instruction,
                id=f"{schedule_id}-run",
                task_queue=TEMPORAL_TASK_QUEUE,
            ),
            spec=ScheduleSpec(cron_expressions=[cron], end_at=end_at),
        ),
    )


async def cancel_job_schedule(client: Client, job_id: str) -> bool:
    schedule_id = _schedule_id(job_id)
    if not await _schedule_exists(client, schedule_id):
        return False
    await client.get_schedule_handle(schedule_id).delete()
    return True


async def list_job_schedules(client: Client) -> list[dict[str, str]]:
    jobs = []
    async for schedule in await client.list_schedules(f"ScheduleId STARTS_WITH '{JOB_SCHEDULE_PREFIX}'"):
        jobs.append({"job_id": schedule.id.removeprefix(JOB_SCHEDULE_PREFIX)})
    return jobs


async def start_once(client: Client, job_id: str, instruction: str, run_in_minutes: int) -> WorkflowHandle:
    workflow_id = f"{ONCE_WORKFLOW_PREFIX}{job_id}"
    return await client.start_workflow(
        RunAgentInstructionWorkflow.run,
        instruction,
        id=workflow_id,
        task_queue=TEMPORAL_TASK_QUEUE,
        start_delay=timedelta(minutes=run_in_minutes),
    )


async def cancel_once(client: Client, job_id: str) -> bool:
    try:
        await client.get_workflow_handle(f"{ONCE_WORKFLOW_PREFIX}{job_id}").cancel()
        return True
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        raise


async def start_deep_research(
    client: Client, budget_usd: float, sleep_hours: float, start_delay_minutes: int = 0
) -> WorkflowHandle:
    """Each call gets a fresh timestamped+random workflow id (unlike start_once's
    caller-chosen job_id) since deep research is meant to be re-run night after night rather
    than tracked as a single named job; the random suffix avoids a collision if two runs are
    ever kicked off within the same second."""
    workflow_id = f"{DEEP_RESEARCH_WORKFLOW_PREFIX}{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
    return await client.start_workflow(
        DeepResearchWorkflow.run,
        args=[budget_usd, sleep_hours],
        id=workflow_id,
        task_queue=TEMPORAL_TASK_QUEUE,
        start_delay=timedelta(minutes=start_delay_minutes),
    )


async def list_once_jobs(client: Client) -> list[dict[str, str]]:
    jobs = []
    query = f"WorkflowId STARTS_WITH '{ONCE_WORKFLOW_PREFIX}' AND ExecutionStatus = 'Running'"
    async for wf in client.list_workflows(query):
        jobs.append({"job_id": wf.id.removeprefix(ONCE_WORKFLOW_PREFIX)})
    return jobs
