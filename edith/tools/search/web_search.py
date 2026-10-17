"""web_search tool, plus grounded_search — the one web-grounded LLM call every
search-shaped tool (web, YouTube, news, deep research) goes through.

Uses Gemini's Google Search grounding when GEMINI_API_KEY is set, otherwise
OpenRouter's web plugin on the main model, so search works with only an
OpenRouter key. A separate single-turn call rather than grounding every
request, to keep search cost and latency scoped to turns that need it.
"""

import logging
from typing import Any

from google.genai import types

from edith.config import DEFAULT_MODEL
from edith.memory.storage import qdrant
from edith.tools.base import ToolContext, tool

logger = logging.getLogger("edith.tools.web_search")


def grounded_search(genai_client: Any, genai_model: str, llm_client: Any, llm_model: str, prompt: str) -> str:
    if genai_client is not None:
        resp = genai_client.models.generate_content(
            model=genai_model,
            contents=prompt,
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
        return resp.text or ""
    resp = llm_client.chat.completions.create(
        model=llm_model,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"plugins": [{"id": "web"}]},
    )
    return resp.choices[0].message.content or ""


def plain_completion(genai_client: Any, genai_model: str, llm_client: Any, llm_model: str, prompt: str) -> str:
    if genai_client is not None:
        return genai_client.models.generate_content(model=genai_model, contents=prompt).text or ""
    resp = llm_client.chat.completions.create(model=llm_model, messages=[{"role": "user", "content": prompt}])
    return resp.choices[0].message.content or ""


def search_ctx(ctx: ToolContext) -> tuple[Any, str, Any, str]:
    return ctx.genai_client, ctx.genai_model, ctx.llm_client, ctx.settings.model if ctx.settings else DEFAULT_MODEL


@tool
def web_search(ctx: ToolContext, query: str) -> str:
    """Search the live web for current information (news, prices, facts you
    aren't confident about, anything time-sensitive). Costs extra latency
    and money, so only call this when the answer genuinely requires it —
    don't call it for things you already know or that are in memory.
    """
    # Recorded before the call resolves — what the user's asking about is the
    # useful signal for understanding them, independent of whether the search
    # itself succeeds.
    qdrant.upsert(ctx.qdrant_client, ctx.llm_client, "search_query", query)
    try:
        text = grounded_search(*search_ctx(ctx), f"Search the web and answer concisely, with sources: {query}")
        return text or "No results found."
    except Exception as e:  # noqa: BLE001 — surface as a tool error, don't crash the loop
        logger.exception("web_search failed for query=%r", query)
        return f"ERROR: web search failed: {e}"
