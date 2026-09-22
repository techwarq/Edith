"""Opt-in web_search tool.

Uses Gemini's own native Google Search grounding (google.genai's
`google_search` tool via `models.generate_content`), not OpenRouter's
":online" model suffix — Gemini already has first-party web search, so
routing it through a second provider was redundant. Implemented as a
separate, single-turn call rather than blanket-enabling grounding on every
request, to keep search cost and latency scoped to only the turns that
actually need it.
"""

import logging

from google import genai
from google.genai import types
from qdrant_client import QdrantClient

from edith.memory import vectors
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.tools.web_search")


def register(registry: ToolRegistry, client: genai.Client, model: str, qdrant_client: QdrantClient | None = None) -> None:
    def web_search(query: str) -> str:
        # Recorded before the call resolves — what the user's asking about is the
        # useful signal for understanding them, independent of whether the search
        # itself succeeds.
        vectors.upsert(qdrant_client, client, "search_query", query)
        try:
            resp = client.models.generate_content(
                model=model,
                contents=f"Search the web and answer concisely, with sources: {query}",
                config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
            )
            return resp.text or "No results found."
        except Exception as e:  # noqa: BLE001 — surface as a tool error, don't crash the loop
            logger.exception("web_search failed for query=%r", query)
            return f"ERROR: web search failed: {e}"

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the live web for current information (news, prices, facts you "
                    "aren't confident about, anything time-sensitive). Costs extra latency "
                    "and money, so only call this when the answer genuinely requires it — "
                    "don't call it for things you already know or that are in memory."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        web_search,
    )
