"""track_url / untrack_url / list_tracked_urls tools.

The list of URLs the nightly reflection job monitors is settings rows with a fixed
category ("tracked_url"),
rather than introducing a new table, since the underlying storage need (a
keyed, upsertable list) is identical.
"""

from edith.memory.records import system
from edith.tools.base import ToolContext, tool

TRACKED_URL_CATEGORY = "tracked_url"


@tool
def track_url(ctx: ToolContext, url: str, note: str = "") -> str:
    """Add a URL to the list of sites monitored by the nightly reflection job
    (daily news/updates check). Use when the user shares a link and asks you
    to keep an eye on it or follow it going forward.

    Args:
        note: Optional short note on why this URL matters / what to watch for on it.
    """
    system.set_setting(ctx.conn, key=url, value=note or url, category=TRACKED_URL_CATEGORY)
    return f"Now tracking {url}."


@tool
def untrack_url(ctx: ToolContext, url: str) -> str:
    """Stop monitoring a previously tracked URL."""
    removed = system.delete_setting(ctx.conn, url)
    return f"Stopped tracking {url}." if removed else f"{url} wasn't being tracked."


@tool
def list_tracked_urls(ctx: ToolContext) -> str:
    """List every URL currently being monitored by the nightly reflection job."""
    facts = system.list_settings(ctx.conn, TRACKED_URL_CATEGORY)
    if not facts:
        return "No URLs are being tracked yet."
    return "\n".join(f"{f['key']} — {f['value']}" for f in facts)
