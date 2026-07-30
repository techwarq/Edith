"""Opt-in get_news tool — same Gemini grounded-search pattern as web_search,
but prompted specifically for recency and a spoken-friendly headline format
(this is what backs "read me the news"), rather than a generic prose answer.
"""

import logging

from google import genai
from google.genai import types

from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.tools.news")


def fetch_news(client: genai.Client, model: str, topic: str = "") -> str:
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
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
        return resp.text or "No recent news found."
    except Exception as e:  # noqa: BLE001 — surface as a tool error, don't crash the loop
        logger.exception("get_news failed for topic=%r", topic)
        return f"ERROR: news fetch failed: {e}"


def register(registry: ToolRegistry, client: genai.Client, model: str) -> None:
    def get_news(topic: str = "") -> str:
        return fetch_news(client, model, topic)

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "get_news",
                "description": (
                    "Fetch recent news headlines, optionally scoped to a topic (e.g. 'startup', "
                    "'aviation'). Call this when the user says 'news' or asks what's happening in a "
                    "space — if they don't name a topic, check their saved facts/preferences first for "
                    "one before asking them or calling with no topic."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"topic": {"type": "string", "description": "Optional topic to scope the news to"}},
                },
            },
        },
        get_news,
    )
