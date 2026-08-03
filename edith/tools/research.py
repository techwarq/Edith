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

from google import genai
from google.genai import types
from qdrant_client import QdrantClient

from edith.memory import vectors
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.tools.research")

MAX_SUBQUESTIONS = 4


def _decompose(client: genai.Client, model: str, query: str) -> list[str]:
    resp = client.models.generate_content(
        model=model,
        contents=(
            f"Break this research question into at most {MAX_SUBQUESTIONS} focused "
            "sub-questions that together cover it well. Reply with ONLY a JSON array "
            f"of strings, no other text.\n\nQuestion: {query}"
        ),
    )
    text = (resp.text or "").strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    try:
        parsed = json.loads(text)
        subquestions = [str(q).strip() for q in parsed if str(q).strip()]
    except (json.JSONDecodeError, TypeError):
        subquestions = []
    return subquestions[:MAX_SUBQUESTIONS] or [query]


def _grounded_answer(client: genai.Client, model: str, question: str) -> str:
    try:
        resp = client.models.generate_content(
            model=model,
            contents=f"Search the web and answer concisely, with sources: {question}",
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
        return resp.text or "(no results)"
    except Exception as e:  # noqa: BLE001 — one failed sub-question shouldn't sink the whole report
        logger.exception("deep_research sub-question failed for %r", question)
        return f"(search failed: {e})"


def _synthesize(client: genai.Client, model: str, query: str, findings: list[tuple[str, str]]) -> str:
    findings_text = "\n\n".join(f"Sub-question: {q}\nFindings: {a}" for q, a in findings)
    prompt = (
        f"You gathered the following research findings for this question:\n{query}\n\n"
        f"{findings_text}\n\n"
        "Synthesize a single clear, well-organized answer to the original question. Only "
        "state what's actually supported by the findings above — if something is thin, "
        "unconfirmed, or a search failed, say so explicitly rather than filling the gap "
        "yourself. End with a short Sources list drawn from the findings."
    )
    resp = client.models.generate_content(model=model, contents=prompt)
    return resp.text or "Could not synthesize a research report from the gathered findings."


def register(
    registry: ToolRegistry, client: genai.Client, model: str, qdrant_client: QdrantClient | None = None
) -> None:
    def deep_research(query: str) -> str:
        vectors.upsert(qdrant_client, client, "search_query", query)
        subquestions = _decompose(client, model, query)
        findings = [(q, _grounded_answer(client, model, q)) for q in subquestions]
        return _synthesize(client, model, query, findings)

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "deep_research",
                "description": (
                    "Multi-step research on a topic: decomposes the question into sub-questions, "
                    "runs a grounded web search per sub-question, and synthesizes one sourced answer "
                    "with gaps or thin sources explicitly flagged. Slower and more expensive than "
                    "web_search (several search calls, not one) — use only for genuinely thorough, "
                    "multi-angle requests, not a quick single-fact lookup."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "The research question."}},
                    "required": ["query"],
                },
            },
        },
        deep_research,
    )
