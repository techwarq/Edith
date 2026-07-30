"""schedule_job / schedule_once / cancel_job / list_jobs tools — general-purpose
recurring and one-off job scheduling backed by Temporal Cloud. Every job runs as
the same RunAgentInstructionWorkflow (see edith/temporal/workflows.py); output
lands in the dedicated jobs session, viewable via the /jobs command.

Tool functions are sync (matching the rest of the tool registry) and use
asyncio.run per call to talk to the async Temporal client — infrequent,
interactive calls, so a fresh event loop each time is fine.
"""

import asyncio
from datetime import datetime, timezone

from edith.config import DEEP_RESEARCH_BUDGET_USD, DEEP_RESEARCH_SLEEP_HOURS, Settings
from edith.temporal import schedules
from edith.temporal.client import TemporalNotConfigured, get_client
from edith.tools.registry import ToolRegistry


def register(registry: ToolRegistry, settings: Settings) -> None:
    def schedule_job(job_id: str, instruction: str, cron: str, end_date: str = "") -> str:
        end_at = None
        if end_date:
            try:
                end_at = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            except ValueError:
                return f"ERROR: end_date must be in YYYY-MM-DD format, got {end_date!r}."

        async def _do() -> None:
            client = await get_client(settings)
            await schedules.create_job_schedule(client, job_id, instruction, cron, end_at)

        try:
            asyncio.run(_do())
        except (TemporalNotConfigured, ValueError) as e:
            return f"ERROR: {e}"
        suffix = f", ending after {end_date}" if end_date else ""
        return f"Scheduled recurring job '{job_id}' (cron: {cron}{suffix}). Output will show up via /jobs."

    def schedule_once(job_id: str, instruction: str, run_in_minutes: int) -> str:
        async def _do() -> None:
            client = await get_client(settings)
            await schedules.start_once(client, job_id, instruction, run_in_minutes)

        try:
            asyncio.run(_do())
        except TemporalNotConfigured as e:
            return f"ERROR: {e}"
        return f"Job '{job_id}' will run once in {run_in_minutes} minute(s). Output will show up via /jobs."

    def cancel_job(job_id: str) -> str:
        async def _do() -> bool:
            client = await get_client(settings)
            if await schedules.cancel_job_schedule(client, job_id):
                return True
            return await schedules.cancel_once(client, job_id)

        try:
            cancelled = asyncio.run(_do())
        except TemporalNotConfigured as e:
            return f"ERROR: {e}"
        return f"Cancelled '{job_id}'." if cancelled else f"No job named '{job_id}' was found."

    def enable_nightly_reflection() -> str:
        async def _do() -> None:
            client = await get_client(settings)
            await schedules.ensure_nightly_reflection_schedule(client)

        try:
            asyncio.run(_do())
        except TemporalNotConfigured as e:
            return f"ERROR: {e}"
        return (
            f"Nightly reflection enabled (cron: {settings.nightly_reflection_cron}). "
            "A Temporal worker process must be running for it to actually fire."
        )

    def disable_nightly_reflection() -> str:
        async def _do() -> bool:
            client = await get_client(settings)
            return await schedules.cancel_nightly_reflection(client)

        try:
            disabled = asyncio.run(_do())
        except TemporalNotConfigured as e:
            return f"ERROR: {e}"
        return "Nightly reflection disabled." if disabled else "Nightly reflection wasn't enabled."

    def start_deep_research(start_delay_minutes: int = 0) -> str:
        async def _do() -> None:
            client = await get_client(settings)
            await schedules.start_deep_research(
                client, DEEP_RESEARCH_BUDGET_USD, DEEP_RESEARCH_SLEEP_HOURS, start_delay_minutes
            )

        try:
            asyncio.run(_do())
        except TemporalNotConfigured as e:
            return f"ERROR: {e}"
        return (
            f"Deep research started (budget ${DEEP_RESEARCH_BUDGET_USD:.2f}, "
            f"~{DEEP_RESEARCH_SLEEP_HOURS:.0f}h between rounds). It runs 3 rounds overnight — broad "
            "scan, elimination, final synthesis — and lands the final 3-4 ideas via /jobs plus a "
            "push notification when the last round finishes."
        )

    def list_jobs() -> str:
        async def _do() -> tuple[list[dict], list[dict]]:
            client = await get_client(settings)
            recurring = await schedules.list_job_schedules(client)
            once = await schedules.list_once_jobs(client)
            return recurring, once

        try:
            recurring, once = asyncio.run(_do())
        except TemporalNotConfigured as e:
            return f"ERROR: {e}"
        if not recurring and not once:
            return "No scheduled jobs."
        lines = [f"(recurring) {j['job_id']}" for j in recurring] + [f"(one-off, pending) {j['job_id']}" for j in once]
        return "\n".join(lines)

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "schedule_job",
                "description": (
                    "Schedule a recurring job: at the given cron time, you'll be run again with "
                    "the given instruction (as if the user had just said it to you), and your "
                    "reply is saved for later reading via /jobs and pushed as a phone notification. "
                    "Use for anything the user wants done repeatedly (\"every Monday at 9am, ...\", "
                    "\"check X daily\"). If the user gives a bounded date range (\"every day for a "
                    "week\", \"from the 22nd to the 29th\"), always pass end_date — otherwise the job "
                    "keeps firing forever."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "description": "Short stable name for this job, e.g. 'monday_standup_prep'."},
                        "instruction": {"type": "string", "description": "What you should do each time this fires, written as an instruction to yourself."},
                        "cron": {
                            "type": "string",
                            "description": "Standard 5-field cron expression (minute hour day month weekday), e.g. '0 9 * * 1' for 9am every Monday.",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "Optional last day this should run, format YYYY-MM-DD (inclusive). Omit for an open-ended recurring job.",
                        },
                    },
                    "required": ["job_id", "instruction", "cron"],
                },
            },
        },
        schedule_job,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "schedule_once",
                "description": (
                    "Schedule a one-off job that runs exactly once, after a delay. Use for "
                    "single reminders/alarms (\"remind me in 2 hours to...\", \"set an alarm for "
                    "20 minutes from now\") rather than recurring ones. Sends a push notification "
                    "to the user's phone with the result when it fires, so no separate "
                    "notify-on-completion step is needed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "description": "Short stable name for this job."},
                        "instruction": {"type": "string", "description": "What you should do when this fires, written as an instruction to yourself."},
                        "run_in_minutes": {"type": "integer", "description": "Delay in minutes from now."},
                    },
                    "required": ["job_id", "instruction", "run_in_minutes"],
                },
            },
        },
        schedule_once,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "cancel_job",
                "description": "Cancel a previously scheduled recurring or one-off job by its job_id.",
                "parameters": {
                    "type": "object",
                    "properties": {"job_id": {"type": "string"}},
                    "required": ["job_id"],
                },
            },
        },
        cancel_job,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "enable_nightly_reflection",
                "description": (
                    "Turn on the nightly reflection job: each night it checks tracked URLs "
                    "(see track_url) for anything relevant, saves durable insights to memory, "
                    "and writes a digest readable via /jobs. Off by default — only enable this "
                    "when the user actually asks for it."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        enable_nightly_reflection,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "disable_nightly_reflection",
                "description": "Turn off the nightly reflection job.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        disable_nightly_reflection,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "start_deep_research",
                "description": (
                    "Kick off an overnight deep-research run to find the best 3-4 startup/product "
                    "ideas to build: three budget-capped rounds (broad scan for current momentum, "
                    "elimination on market saturation and willingness-to-pay, final synthesis), "
                    "spread across the night with real sleep between rounds. Use when the user asks "
                    "for deep/overnight research into what to build next, not for quick idea "
                    "brainstorming in-chat."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_delay_minutes": {
                            "type": "integer",
                            "description": "Minutes from now to start the first round (default 0, start immediately).",
                        }
                    },
                },
            },
        },
        start_deep_research,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_jobs",
                "description": "List every currently scheduled recurring job and pending one-off job.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        list_jobs,
    )
