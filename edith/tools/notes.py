"""save_fact / update_fact / forget_fact / recall_fact / search_history tools.

These give the model direct read/write access to its own memory of you.
save_fact and update_fact behave identically (upsert on key) — both are
exposed so the model's tool choice reads naturally either way.
"""

import sqlite3

from google import genai
from qdrant_client import QdrantClient

from edith.memory import search as memory_search
from edith.memory import store, vectors
from edith.tools.registry import ToolRegistry


def register(
    registry: ToolRegistry,
    conn: sqlite3.Connection,
    qdrant_client: QdrantClient | None = None,
    genai_client: genai.Client | None = None,
) -> None:
    def save_fact(key: str, value: str, category: str = "") -> str:
        # Fetched before the write so a same-key update doesn't see itself as a "duplicate".
        others = (
            [f for f in store.get_facts_by_category(conn, category) if f["key"] != key]
            if category
            else []
        )
        store.save_fact(conn, key=key, value=value, category=category or None)
        vectors.upsert(qdrant_client, genai_client, "fact", f"{key}: {value}", category=category or "")
        result = f"Saved: {key} = {value}"
        if others:
            existing = "; ".join(f"{f['key']}={f['value']}" for f in others)
            result += (
                f"\n(Other '{category}' facts already stored — check for overlap/conflict "
                f"and forget_fact whichever is now stale: {existing})"
            )
        return result

    def forget_fact(key: str) -> str:
        removed = store.forget_fact(conn, key)
        return f"Forgot '{key}'." if removed else f"No fact named '{key}' was stored."

    def recall_fact(key: str) -> str:
        value = store.get_fact(conn, key)
        return value if value is not None else f"No fact named '{key}' is stored."

    def search_history(query: str) -> str:
        results = memory_search.search_history(conn, query)
        if not results:
            return "No matching past messages found."
        lines = [f"[{r['created_at']}] {r['role']}: {r['content']}" for r in results]
        return "\n".join(lines)

    def semantic_search(query: str) -> str:
        results = vectors.semantic_search(qdrant_client, genai_client, query)
        if not results:
            return "No related memories found." if qdrant_client else "Semantic memory isn't configured yet."
        lines = [f"[{r['type']}, score={r['score']:.2f}] {r['text']}" for r in results]
        return "\n".join(lines)

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "save_fact",
                "description": (
                    "Save or update a durable fact about the user in long-term memory "
                    "(e.g. their role, preferences, ongoing projects). Use a short, stable "
                    "key so future updates overwrite the same fact rather than duplicating it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Short stable identifier, e.g. 'current_role'"},
                        "value": {"type": "string", "description": "The fact's value"},
                        "category": {
                            "type": "string",
                            "description": (
                                "Optional grouping: identity, preference, project, fact, or behavior (how "
                                "the user wants you to act) — behavior facts get surfaced to you as "
                                "directives, not just background. Do NOT use category='goal' here — if the "
                                "user states something they're working toward with real scope, call "
                                "create_goal instead so it shows up in their Goals dashboard tab."
                            ),
                        },
                    },
                    "required": ["key", "value"],
                },
            },
        },
        save_fact,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "update_fact",
                "description": "Update an existing fact about the user. Same as save_fact (upserts by key).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "category": {"type": "string"},
                    },
                    "required": ["key", "value"],
                },
            },
        },
        save_fact,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "forget_fact",
                "description": "Delete a previously saved fact about the user. Confirm with the user before calling this.",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
            },
        },
        forget_fact,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "recall_fact",
                "description": "Look up a single previously saved fact about the user by its key.",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
            },
        },
        recall_fact,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "search_history",
                "description": (
                    "Exact keyword search over past conversation history with the user. "
                    "Use this when the user references something specific from an earlier "
                    "session (a name, a term) that isn't in the current context window."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        search_history,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "semantic_search",
                "description": (
                    "Meaning-based search across everything you know about the user — facts, past "
                    "messages, what they've searched for, and uploaded documents — even when the "
                    "wording doesn't match. Use this to find what's *related* to a topic (patterns, "
                    "context, prior interest) rather than an exact phrase. Prefer search_history when "
                    "you need an exact quote; prefer this when you're trying to understand or connect "
                    "something about the user."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        semantic_search,
    )
