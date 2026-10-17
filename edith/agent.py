"""Core agent loop.

Contract: Agent.handle_turn(session_id, text) -> text. No print()/input()
anywhere in this module (or llm/, memory/, tools/) — that's what lets a
future interfaces/voice.py do STT -> handle_turn -> TTS without touching
the core.
"""

import json
import logging
import sqlite3
from typing import Callable, Optional

import openai

from edith.config import MAX_CONTEXT_TURNS
from edith.llm.client import ContextLengthExceeded, run_completion_with_tools
from edith.memory import conversation
from edith.memory.brain import Brain
from edith.memory.records import planning
from edith.observability.tracing import Recorder
from edith.prompts import build_system_prompt
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.agent")

AUTO_RECALL_K = 3

# Tool-call argument names that point at a structured record; the turn's note is
# linked to whatever records the turn touched (memory_refs).
RECORD_ARGS = {
    "goal_id": "goal",
    "milestone_id": "milestone",
    "todo_id": "todo",
    "item_id": "idea_bug",
    "application_id": "job_application",
    "lead_id": "startup_lead",
    "prospect_id": "outreach_prospect",
}


class Agent:
    def __init__(
        self,
        conn: sqlite3.Connection,
        client: openai.OpenAI,
        model: str,
        registry: ToolRegistry,
        brain: Brain | None = None,
    ) -> None:
        self.conn = conn
        self.client = client
        self.model = model
        self.registry = registry
        self.brain = brain or Brain(conn)

    def handle_turn(self, session_id: str, user_text: str, on_progress: Optional[Callable[[str], None]] = None) -> str:
        conversation.add_message(self.conn, session_id, "user", content=user_text)
        recorder = Recorder(self.conn, session_id, kind="turn", input_text=user_text)
        memories = self._recall(user_text)

        max_turns = MAX_CONTEXT_TURNS
        for attempt in range(2):
            core = self.brain.core()
            goals = planning.list_goals(self.conn, "active")
            open_todos = [t for t in planning.list_todos(self.conn) if t["status"] != "done"]
            system_prompt = build_system_prompt(core, goals, open_todos, memories)
            history = conversation.get_working_messages(self.conn, session_id, max_turns)
            messages = [{"role": "system", "content": system_prompt}] + history

            try:
                final_text, new_messages = run_completion_with_tools(
                    self.client,
                    messages,
                    self.registry.schemas(),
                    self.model,
                    self.registry.dispatch,
                    on_progress,
                    recorder,
                )
                self._persist_new_messages(session_id, new_messages)
                recorder.finish(final_text)
                if not _called(new_messages, "remember"):
                    self.brain.remember_later(
                        f"User: {user_text}\nEddy: {final_text}",
                        session_id=session_id,
                        refs=_touched_records(new_messages),
                    )
                return final_text
            except ContextLengthExceeded:
                if attempt == 0:
                    max_turns = max(1, max_turns // 2)
                    continue
                reply = (
                    "Sorry — this conversation has gotten too long for the model's context "
                    "window, even after trimming. Try `/new` to start a fresh session."
                )
                recorder.finish(reply, status="error", error="context_length_exceeded")
                return reply
            except openai.AuthenticationError:
                logger.error("OpenRouter authentication failed")
                reply = "ERROR: OpenRouter authentication failed — check your OPENROUTER_API_KEY."
                recorder.finish(reply, status="error", error="authentication_failed")
                return reply
            except openai.APIError as e:
                logger.exception("OpenRouter API error")
                reply = f"Sorry, I hit an error talking to the model: {e}"
                recorder.finish(reply, status="error", error=str(e))
                return reply

        reply = "Sorry, something went wrong handling that."  # unreachable in practice
        recorder.finish(reply, status="error", error="unreachable")
        return reply

    def _recall(self, user_text: str) -> list[dict]:
        try:
            return self.brain.recall(user_text, k=AUTO_RECALL_K, include_core=False)
        except Exception:  # noqa: BLE001 — a failed recall should cost context, not the turn
            logger.exception("Brain auto-recall failed")
            return []

    def _persist_new_messages(self, session_id: str, new_messages: list[dict]) -> None:
        for msg in new_messages:
            role = msg["role"]
            if role == "assistant":
                conversation.add_message(
                    self.conn,
                    session_id,
                    "assistant",
                    content=msg.get("content"),
                    tool_calls=msg.get("tool_calls"),
                )
            elif role == "tool":
                conversation.add_message(
                    self.conn,
                    session_id,
                    "tool",
                    content=msg.get("content"),
                    tool_call_id=msg.get("tool_call_id"),
                    tool_name=msg.get("name"),
                )


def _touched_records(new_messages: list[dict]) -> list[tuple[str, int]]:
    refs = []
    for msg in new_messages:
        for call in msg.get("tool_calls") or []:
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            for arg, kind in RECORD_ARGS.items():
                if isinstance(args, dict) and isinstance(args.get(arg), int) and args[arg] > 0:
                    refs.append((kind, args[arg]))
    return list(dict.fromkeys(refs))


def _called(new_messages: list[dict], tool_name: str) -> bool:
    return any(
        call.get("function", {}).get("name") == tool_name
        for msg in new_messages
        for call in msg.get("tool_calls") or []
    )
