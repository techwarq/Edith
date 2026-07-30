"""Core agent loop.

Contract: Agent.handle_turn(session_id, text) -> text. No print()/input()
anywhere in this module (or llm/, memory/, tools/) — that's what lets a
future interfaces/voice.py do STT -> handle_turn -> TTS without touching
the core.
"""

import logging
import sqlite3
from typing import Callable, Optional

import openai
from google import genai
from qdrant_client import QdrantClient

from edith.config import MAX_CONTEXT_TURNS
from edith.llm.client import ContextLengthExceeded, run_completion_with_tools
from edith.memory import goals_store, store, todos_store, vectors
from edith.observability.tracing import Recorder
from edith.prompts import build_system_prompt
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.agent")


class Agent:
    def __init__(
        self,
        conn: sqlite3.Connection,
        client: openai.OpenAI,
        model: str,
        registry: ToolRegistry,
        qdrant_client: QdrantClient | None = None,
        genai_client: genai.Client | None = None,
    ) -> None:
        self.conn = conn
        self.client = client
        self.model = model
        self.registry = registry
        self.qdrant_client = qdrant_client
        self.genai_client = genai_client

    def handle_turn(self, session_id: str, user_text: str, on_progress: Optional[Callable[[str], None]] = None) -> str:
        store.add_message(self.conn, session_id, "user", content=user_text)
        vectors.upsert(self.qdrant_client, self.genai_client, "message", user_text, session_id=session_id, role="user")
        recorder = Recorder(self.conn, session_id, kind="turn", input_text=user_text)

        max_turns = MAX_CONTEXT_TURNS
        for attempt in range(2):
            facts = store.get_all_facts(self.conn)
            goals = goals_store.list_goals(self.conn, "active")
            open_todos = [t for t in todos_store.list_todos(self.conn) if t["status"] != "done"]
            system_prompt = build_system_prompt(facts, goals, open_todos)
            history = store.get_working_messages(self.conn, session_id, max_turns)
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

    def _persist_new_messages(self, session_id: str, new_messages: list[dict]) -> None:
        for msg in new_messages:
            role = msg["role"]
            if role == "assistant":
                store.add_message(
                    self.conn,
                    session_id,
                    "assistant",
                    content=msg.get("content"),
                    tool_calls=msg.get("tool_calls"),
                )
                if msg.get("content"):
                    vectors.upsert(
                        self.qdrant_client, self.genai_client, "message", msg["content"],
                        session_id=session_id, role="assistant",
                    )
            elif role == "tool":
                store.add_message(
                    self.conn,
                    session_id,
                    "tool",
                    content=msg.get("content"),
                    tool_call_id=msg.get("tool_call_id"),
                    tool_name=msg.get("name"),
                )
