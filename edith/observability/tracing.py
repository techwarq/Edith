"""Trace/span recording — one `traces` row per agent turn (or eval run), one
`spans` row per LLM call / tool call made while handling it.

Modeled loosely on the trace/span vocabulary from arXiv:2503.06745 ("Beyond
Black-Box Benchmarking": agent observability needs execution-flow-level spans,
not just outcome metrics) but implemented directly against the existing
SQLite store rather than an OTel SDK — same "just SQLite, no new infra"
pattern as the rest of edith/memory. A Recorder is created once per
Agent.handle_turn call and threaded through the LLM/tool-call loop; passing
`recorder=None` (the default everywhere it's threaded through) disables
tracing entirely, so existing callers/tests are unaffected.
"""

import json
import sqlite3
import time
import uuid
from typing import Any, Optional

from edith.observability.pricing import estimate_llm_cost

_PREVIEW_CHARS = 4000  # cap span input/output text so one huge tool result (e.g. a Drive file dump) can't bloat the DB


def _truncate(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    return text if len(text) <= _PREVIEW_CHARS else text[:_PREVIEW_CHARS] + "…(truncated)"


class Recorder:
    def __init__(
        self,
        conn: sqlite3.Connection,
        session_id: Optional[str],
        kind: str = "turn",
        input_text: Optional[str] = None,
    ) -> None:
        self.conn = conn
        self.trace_id = uuid.uuid4().hex
        self._t0 = time.monotonic()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_usd = 0.0
        conn.execute(
            "INSERT INTO traces (id, session_id, kind, input) VALUES (?, ?, ?, ?)",
            (self.trace_id, session_id, kind, _truncate(input_text)),
        )

    def record_llm_span(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        output_preview: Optional[str],
        duration_ms: float,
        status: str = "ok",
        error: Optional[str] = None,
    ) -> None:
        cost = estimate_llm_cost(model, prompt_tokens, completion_tokens)
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.cost_usd += cost
        self.conn.execute(
            "INSERT INTO spans (trace_id, kind, name, output, status, error, duration_ms, "
            "prompt_tokens, completion_tokens, cost_usd) VALUES (?, 'llm', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.trace_id,
                model,
                _truncate(output_preview),
                status,
                error,
                duration_ms,
                prompt_tokens,
                completion_tokens,
                cost,
            ),
        )

    def record_tool_span(
        self,
        name: str,
        args: dict[str, Any],
        output_preview: Optional[str],
        duration_ms: float,
        status: str = "ok",
        error: Optional[str] = None,
    ) -> None:
        try:
            args_json = _truncate(json.dumps(args))
        except TypeError:
            args_json = _truncate(str(args))
        self.conn.execute(
            "INSERT INTO spans (trace_id, kind, name, input, output, status, error, duration_ms) "
            "VALUES (?, 'tool', ?, ?, ?, ?, ?, ?)",
            (self.trace_id, name, args_json, _truncate(output_preview), status, error, duration_ms),
        )

    def finish(self, output: Optional[str], status: str = "ok", error: Optional[str] = None) -> str:
        duration_ms = (time.monotonic() - self._t0) * 1000
        self.conn.execute(
            "UPDATE traces SET output = ?, status = ?, error = ?, "
            "ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), duration_ms = ?, "
            "prompt_tokens = ?, completion_tokens = ?, cost_usd = ? WHERE id = ?",
            (
                _truncate(output),
                status,
                error,
                duration_ms,
                self.prompt_tokens,
                self.completion_tokens,
                self.cost_usd,
                self.trace_id,
            ),
        )
        return self.trace_id
