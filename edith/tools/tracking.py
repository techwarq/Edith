"""track_url / untrack_url / list_tracked_urls tools.

The list of URLs the nightly reflection job monitors is just facts with a fixed
category ("tracked_url") — reuses save_fact/forget_fact/get_facts_by_category
rather than introducing a new table, since the underlying storage need (a
keyed, upsertable list) is identical.
"""

import sqlite3

from edith.memory import store
from edith.tools.registry import ToolRegistry

TRACKED_URL_CATEGORY = "tracked_url"


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def track_url(url: str, note: str = "") -> str:
        store.save_fact(conn, key=url, value=note or url, category=TRACKED_URL_CATEGORY)
        return f"Now tracking {url}."

    def untrack_url(url: str) -> str:
        removed = store.forget_fact(conn, url)
        return f"Stopped tracking {url}." if removed else f"{url} wasn't being tracked."

    def list_tracked_urls() -> str:
        facts = store.get_facts_by_category(conn, TRACKED_URL_CATEGORY)
        if not facts:
            return "No URLs are being tracked yet."
        return "\n".join(f"{f['key']} — {f['value']}" for f in facts)

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "track_url",
                "description": (
                    "Add a URL to the list of sites monitored by the nightly reflection job "
                    "(daily news/updates check). Use when the user shares a link and asks you "
                    "to keep an eye on it or follow it going forward."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "note": {
                            "type": "string",
                            "description": "Optional short note on why this URL matters / what to watch for on it.",
                        },
                    },
                    "required": ["url"],
                },
            },
        },
        track_url,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "untrack_url",
                "description": "Stop monitoring a previously tracked URL.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        untrack_url,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_tracked_urls",
                "description": "List every URL currently being monitored by the nightly reflection job.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        list_tracked_urls,
    )
