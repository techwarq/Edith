"""remember / recall / forget_memory / search_history tools — the model's handle on
its own brain (edith/memory/brain) and on raw conversation history.

Most memories are written automatically after each turn; remember is for when the
user explicitly asks, or when a tool result surfaced something worth filing."""

from edith.memory import conversation
from edith.memory.brain import format_notes
from edith.tools.base import ToolContext, tool


@tool
def remember(ctx: ToolContext, content: str, region: str = "") -> str:
    """Store something in long-term memory right now. The brain decides which region of
    the user's life it belongs to, whether it's a core memory, and links it to related
    memories. Write content as a clear standalone statement about the user.

    Args:
        content: What to remember, e.g. 'Sonali prefers calls after 4pm'
        region: Optional region to file it under (e.g. 'content strategy'); leave empty to let the brain decide
    """
    if not ctx.brain or not ctx.brain.can_think:
        return "Memory isn't configured (needs a Gemini key)."
    note = ctx.brain.remember(content, source="explicit", region=region or None)
    if note is None:
        return "Not stored — the brain judged there was nothing lasting in that."
    core = ", core" if note["core"] else ""
    return f"Remembered as #{note['id']} in '{note['region']}'{core}: {note['context']}"


@tool
def recall(ctx: ToolContext, query: str) -> str:
    """Meaning-based search of long-term memory about the user — returns the closest
    memories plus the memories linked to them, even when the wording differs. Use to
    understand or connect something about the user (patterns, context, prior interest).
    Prefer search_history for an exact quote from a past conversation.
    """
    found = ctx.brain.recall(query) if ctx.brain else []
    return format_notes(found) if found else "No related memories found."


@tool
def forget_memory(ctx: ToolContext, note_id: int) -> str:
    """Delete one memory (and its links) by its #id — when it's wrong or the user asks
    you to forget it. Confirm with the user first unless they explicitly asked.

    Args:
        note_id: The memory's number, shown like #12 in recall results
    """
    if ctx.brain and ctx.brain.forget(note_id):
        return f"Forgot memory #{note_id}."
    return f"No memory #{note_id} exists."


@tool
def search_history(ctx: ToolContext, query: str) -> str:
    """Exact keyword search over past conversation history with the user.
    Use this when the user references something specific from an earlier
    session (a name, a term) that isn't in the current context window.
    """
    results = conversation.search_history(ctx.conn, query)
    if not results:
        return "No matching past messages found."
    lines = [f"[{r['created_at']}] {r['role']}: {r['content']}" for r in results]
    return "\n".join(lines)
