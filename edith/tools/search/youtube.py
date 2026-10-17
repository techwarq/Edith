"""Opt-in open_youtube tool — resolves a video/channel/podcast request to a
real YouTube URL via the same Gemini grounded-search pattern as web_search,
then returns it as a plain link in the reply. Deliberately no custom
frontend/native plumbing yet: ship the plain link first and see whether
Android's default link handling already hands youtube.com URLs to the
installed YouTube app before investing in a Capacitor plugin + app rebuild.
"""

import logging
import re

from edith.tools.base import ToolContext, tool
from edith.tools.search.web_search import grounded_search, search_ctx

logger = logging.getLogger("edith.tools.youtube")

_YOUTUBE_URL_RE = re.compile(r"https?://(?:www\.)?(?:youtube\.com/\S+|youtu\.be/\S+)")


@tool
def open_youtube(ctx: ToolContext, query: str) -> str:
    """Find a real YouTube video/channel/podcast episode matching what the user asked
    for by name or topic, and return a link to it — use when the user wants to watch
    or listen to something specific, not for general web research.
    """
    prompt = (
        f"Find the single best-matching YouTube video, channel, or podcast episode for: {query}. "
        "Respond with only the URL, nothing else."
    )
    try:
        text = grounded_search(*search_ctx(ctx), prompt)
    except Exception as e:  # noqa: BLE001 — surface as a tool error, don't crash the loop
        logger.exception("open_youtube failed for query=%r", query)
        return f"ERROR: YouTube search failed: {e}"

    match = _YOUTUBE_URL_RE.search(text)
    if not match:
        return f"Couldn't find a YouTube link for that. Raw result: {text.strip() or '(none)'}"
    url = match.group(0).rstrip(").,\"'")
    return f"Here you go: {url}"
