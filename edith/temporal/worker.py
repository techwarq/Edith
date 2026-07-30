"""Entrypoint: python -m edith.temporal.worker

Connects to Temporal Cloud and polls TEMPORAL_TASK_QUEUE forever. Must be
running for schedule_job/schedule_once/nightly reflection to actually fire —
creating a Temporal Schedule only queues workflow runs, a worker is what
executes them.

Deliberately does NOT auto-create the nightly reflection schedule on startup —
it's opt-in via the enable_nightly_reflection tool (ask Edith), so starting
the worker never silently re-adds a schedule you'd turned off. The nightly
evals schedule is the exception: it's a system health check rather than Edith
acting on your behalf, so it IS created unconditionally here (idempotent) —
see schedules.ensure_nightly_evals_schedule.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.worker import Worker

from edith.config import TEMPORAL_TASK_QUEUE, load_settings
from edith.temporal import activities
from edith.temporal.client import get_client
from edith.temporal.schedules import ensure_nightly_evals_schedule
from edith.temporal.workflows import DeepResearchWorkflow, RunAgentInstructionWorkflow, RunEvalsWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("edith.temporal.worker")


async def main() -> None:
    settings = load_settings()
    client = await get_client(settings)
    try:
        await ensure_nightly_evals_schedule(client)
    except Exception:
        logger.exception("Failed to ensure nightly evals schedule — continuing without it")
    logger.info("Starting worker on task queue %r.", TEMPORAL_TASK_QUEUE)
    worker = Worker(
        client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[RunAgentInstructionWorkflow, RunEvalsWorkflow, DeepResearchWorkflow],
        activities=[
            activities.run_agent_instruction,
            activities.run_nightly_evals,
            activities.run_deep_research_round,
            activities.notify_deep_research_done,
        ],
        activity_executor=ThreadPoolExecutor(max_workers=4),
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
