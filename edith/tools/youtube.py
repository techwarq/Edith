"""Opt-in open_youtube tool — resolves a video/channel/podcast request to a
real YouTube URL via the same Gemini grounded-search pattern as web_search,
then returns it as a plain link in the reply. Deliberately no custom
frontend/native plumbing yet: ship the plain link first and see whether
Android's default link handling already hands youtube.com URLs to the
installed YouTube app before investing in a Capacitor plugin + app rebuild.
"""

import logging
import re

from google import genai
from google.genai import types

from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.tools.youtube")

_YOUTUBE_URL_RE = re.compile(r"https?://(?:www\.)?(?:youtube\.com/\S+|youtu\.be/\S+)")


def register(registry: ToolRegistry, client: genai.Client, model: str) -> None:
    def open_youtube(query: str) -> str:
        prompt = (
            f"Find the single best-matching YouTube video, channel, or podcast episode for: {query}. "
            "Respond with only the URL, nothing else."
        )
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
            )
            text = resp.text or ""
        except Exception as e:  # noqa: BLE001 — surface as a tool error, don't crash the loop
            logger.exception("open_youtube failed for query=%r", query)
            return f"ERROR: YouTube search failed: {e}"

        match = _YOUTUBE_URL_RE.search(text)
        if not match:
            return f"Couldn't find a YouTube link for that. Raw result: {text.strip() or '(none)'}"
        url = match.group(0).rstrip(").,\"'")
        return f"Here you go: {url}"

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "open_youtube",
                "description": (
                    "Find a real YouTube video/channel/podcast episode matching what the user asked "
                    "for by name or topic, and return a link to it — use when the user wants to watch "
                    "or listen to something specific, not for general web research."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        open_youtube,
    )
