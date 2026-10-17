"""deep_research tool — multi-step research mode.

Breaks a query into a handful of sub-questions, runs a grounded web search
(same Gemini google_search grounding as web_search.py) per sub-question, then
synthesizes a single sourced answer. This is the "dedicated multi-step
research-agent mode" that was previously deferred — implemented as a single
tool call rather than a separate CLI mode so it drops straight into the
normal tool loop and inherits the same grounding/honesty rules as everything
else in prompts.py.
"""

import json
import logging

from typing import Any

from edith.memory.storage import qdrant
from edith.tools.base import ToolContext, tool
from edith.tools.search.web_search import grounded_search, plain_completion, search_ctx

logger = logging.getLogger("edith.tools.research")

MAX_SUBQUESTIONS = 4


def _decompose(llm: tuple[Any, str, Any, str], query: str) -> list[str]:
    text = plain_completion(
        *llm,
        f"Break this research question into at most {MAX_SUBQUESTIONS} focused "
        "sub-questions that together cover it well. Reply with ONLY a JSON array "
        f"of strings, no other text.\n\nQuestion: {query}",
    ).strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    try:
        parsed = json.loads(text)
        subquestions = [str(q).strip() for q in parsed if str(q).strip()]
    except (json.JSONDecodeError, TypeError):
        subquestions = []
    return subquestions[:MAX_SUBQUESTIONS] or [query]


def _grounded_answer(llm: tuple[Any, str, Any, str], question: str) -> str:
    try:
        return grounded_search(*llm, f"Search the web and answer concisely, with sources: {question}") or "(no results)"
    except Exception as e:  # noqa: BLE001 — one failed sub-question shouldn't sink the whole report
        logger.exception("deep_research sub-question failed for %r", question)
        return f"(search failed: {e})"


def _synthesize(llm: tuple[Any, str, Any, str], query: str, findings: list[tuple[str, str]]) -> str:
    findings_text = "\n\n".join(f"Sub-question: {q}\nFindings: {a}" for q, a in findings)
    prompt = (
        f"You gathered the following research findings for this question:\n{query}\n\n"
        f"{findings_text}\n\n"
        "Synthesize a single clear, well-organized answer to the original question. Only "
        "state what's actually supported by the findings above — if something is thin, "
        "unconfirmed, or a search failed, say so explicitly rather than filling the gap "
        "yourself. End with a short Sources list drawn from the findings."
    )
    return plain_completion(*llm, prompt) or "Could not synthesize a research report from the gathered findings."


@tool
def deep_research(ctx: ToolContext, query: str) -> str:
    """Multi-step research on a topic: decomposes the question into sub-questions,
    runs a grounded web search per sub-question, and synthesizes one sourced answer
    with gaps or thin sources explicitly flagged. Slower and more expensive than
    web_search (several search calls, not one) — use only for genuinely thorough,
    multi-angle requests, not a quick single-fact lookup.

    Args:
        query: The research question.
    """
    llm = search_ctx(ctx)
    qdrant.upsert(ctx.qdrant_client, ctx.llm_client, "search_query", query)
    subquestions = _decompose(llm, query)
    findings = [(q, _grounded_answer(llm, q)) for q in subquestions]
    return _synthesize(llm, query, findings)
