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
