"""Opt-in get_news tool — same Gemini grounded-search pattern as web_search,
but prompted specifically for recency and a spoken-friendly headline format
(this is what backs "read me the news"), rather than a generic prose answer.
"""

import logging

from typing import Any

from edith.tools.base import ToolContext, tool
from edith.tools.search.web_search import grounded_search, search_ctx

logger = logging.getLogger("edith.tools.news")


def fetch_news(genai_client: Any, genai_model: str, llm_client: Any, llm_model: str, topic: str = "") -> str:
    """Standalone so the Situation Monitor dashboard's Live News panel
    (edith/monitor/api.py) can call the same grounded-search logic without
    going through the tool registry — this is the one function both call."""
    subject = f"about {topic}" if topic else "on general current events"
    prompt = (
        f"Search for recent news headlines {subject} from the last 24-48 hours. "
        "Summarize the top 5 in a spoken-friendly style: one line per item, "
        "headline followed by a one-sentence summary. Include rough dates where relevant."
    )
    try:
        return grounded_search(genai_client, genai_model, llm_client, llm_model, prompt) or "No recent news found."
    except Exception as e:  # noqa: BLE001 — surface as a tool error, don't crash the loop
        logger.exception("get_news failed for topic=%r", topic)
        return f"ERROR: news fetch failed: {e}"


@tool
def get_news(ctx: ToolContext, topic: str = "") -> str:
    """Fetch recent news headlines, optionally scoped to a topic (e.g. 'startup',
    'aviation'). Call this when the user says 'news' or asks what's happening in a
    space — if they don't name a topic, check their saved facts/preferences first for
    one before asking them or calling with no topic.

    Args:
        topic: Optional topic to scope the news to
    """
    return fetch_news(*search_ctx(ctx), topic)
