"""Temporal activities. Deliberately sync (not async) — the entire edith stack
(Agent.handle_turn, browse_url's Playwright calls, the OpenAI/Gemini clients) is
synchronous/blocking, so this activity runs in the Worker's ThreadPoolExecutor
(see worker.py's activity_executor) rather than forcing an async rewrite of code
that's shared with the CLI/server interfaces.
"""

import logging
import sqlite3

from google import genai
from temporalio import activity

from edith.agent import Agent
from edith.config import Settings, load_settings
from edith.llm.client import make_client
from edith.memory import db, store, vectors
from edith.integrations import push

logger = logging.getLogger("edith.temporal.activities")

_agent: Agent | None = None
_jobs_session_id: str | None = None
_conn: sqlite3.Connection | None = None
_settings: Settings | None = None
_client = None  # OpenRouter — reused as the eval judge (different model, same client)


def _get_agent() -> tuple[Agent, str]:
    """Lazily builds one AppContext per worker process (not per activity call) —
    mirrors bootstrap.build_app_context but skips Google/WhatsApp/TTS wiring that
    scheduled jobs don't need."""
    global _agent, _jobs_session_id, _conn, _settings, _client
    if _agent is None:
        from edith.bootstrap import build_registry  # deferred: bootstrap -> tools.scheduling -> temporal.* -> here is a cycle at module-import time

        _settings = load_settings()
        _conn = db.connect(_settings.db_path)
        _client = make_client(_settings.api_key)  # OpenRouter — Agent's tool-calling loop
        genai_client = genai.Client(api_key=_settings.gemini_api_key)  # Gemini native SDK — web_search grounding, embeddings
        qdrant_client = vectors.make_qdrant_client(_settings.qdrant_url, _settings.qdrant_api_key)
        vectors.ensure_collection(qdrant_client)
        registry = build_registry(_conn, genai_client, _settings.gemini_grounding_model, qdrant_client, _settings)
        _agent = Agent(_conn, _client, _settings.model, registry, qdrant_client, genai_client)
        _jobs_session_id = store.get_or_create_jobs_session(_conn, _settings.model)
    return _agent, _jobs_session_id


@activity.defn
def run_agent_instruction(instruction: str) -> str:
    agent, session_id = _get_agent()
    activity.logger.info("Running scheduled instruction (%d chars)", len(instruction))
    reply = agent.handle_turn(session_id, instruction)
    try:
        push.send_push_notification(
            _conn, _settings, title="Edith", body=reply[:200], data={"type": "job_completion"}
        )
    except Exception:
        logger.exception("Failed to send push notification for scheduled job completion")
    return reply


@activity.defn
def run_deep_research_round(instruction: str) -> dict:
    """One phase of DeepResearchWorkflow. Cost is queried back from the traces table
    (recorded by Agent.handle_turn's Recorder) rather than threaded through handle_turn's
    return value, so the workflow can enforce its budget without any pricing/token logic
    leaking into workflow code."""
    agent, session_id = _get_agent()
    activity.logger.info("Deep research round (%d chars)", len(instruction))
    reply = agent.handle_turn(session_id, instruction)
    row = _conn.execute(
        "SELECT cost_usd FROM traces WHERE session_id = ? ORDER BY started_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return {"reply": reply, "cost_usd": row[0] if row else 0.0}


@activity.defn
def notify_deep_research_done(digest: str) -> None:
    _get_agent()  # ensures _conn/_settings are populated even if this is the first activity this worker process runs
    try:
        push.send_push_notification(
            _conn, _settings, title="Edith — Deep Research", body=digest[:200], data={"type": "deep_research_done"}
        )
    except Exception:
        logger.exception("Failed to send push notification for deep research completion")


@activity.defn
def run_nightly_evals() -> str:
    """The nightly data point behind "is Edith getting worse or better" — same
    eval suite the dashboard's "Run evals" button triggers, just on a fixed
    cadence instead of only when someone remembers to click it (see
    edith/observability/evals.py). Failures here are logged, not raised — a
    bad night of evals shouldn't page anyone, it should just show up as a dip
    in the trend chart tomorrow."""
    from edith.observability import evals

    agent, _ = _get_agent()
    try:
        result = evals.run_eval_suite(_conn, agent, _client, _settings.openrouter_text_model)
        activity.logger.info("Nightly evals: run_id=%s, %d case(s)", result["run_id"], len(result["results"]))
        return result["run_id"]
    except Exception:
        logger.exception("Nightly eval run failed")
        return ""
