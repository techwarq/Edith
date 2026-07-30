"""save_social_skill / list_social_skills / recall_social_skills tools.

Lets Edith act as a social-media (X/Instagram) content assistant grounded in
the user's own material — writing style, niche expertise, content pillars,
past post examples — rather than inventing ideas from nothing. Skill content
is stored as facts with a fixed category ("social_skill"), reusing
save_fact/get_facts_by_category the same way tracking.py reuses them for
tracked URLs, plus a matching Qdrant embedding under its own type so
recall_social_skills can search skill content specifically without mixing
in unrelated facts.

Content direction ("what I want to post about, my niche, my goals") is
handled separately via the /skill-talk command (edith/commands.py), which
saves it through the ordinary save_fact tool with category="content_strategy"
— it's the user's stated intent, not reference material, so it doesn't
belong in this same bucket.
"""

import sqlite3

from google import genai
from qdrant_client import QdrantClient

from edith.memory import store, vectors
from edith.tools.registry import ToolRegistry

SOCIAL_SKILL_CATEGORY = "social_skill"


def register(
    registry: ToolRegistry,
    conn: sqlite3.Connection,
    qdrant_client: QdrantClient | None = None,
    genai_client: genai.Client | None = None,
) -> None:
    def save_social_skill(title: str, content: str, platform: str = "") -> str:
        store.save_fact(conn, key=title, value=content, category=SOCIAL_SKILL_CATEGORY)
        vectors.upsert(
            qdrant_client, genai_client, SOCIAL_SKILL_CATEGORY, f"{title}: {content}", platform=platform or "general"
        )
        return f"Saved social skill '{title}'."

    def list_social_skills() -> str:
        facts = store.get_facts_by_category(conn, SOCIAL_SKILL_CATEGORY)
        if not facts:
            return "No social media skill files saved yet."
        lines = []
        for f in facts:
            preview = f["value"] if len(f["value"]) <= 120 else f["value"][:120] + "..."
            lines.append(f"{f['key']} — {preview}")
        return "\n".join(lines)

    def recall_social_skills(query: str) -> str:
        results = vectors.semantic_search(qdrant_client, genai_client, query, type_filter=SOCIAL_SKILL_CATEGORY)
        if not results:
            return "No matching social skill content found." if qdrant_client else "Semantic memory isn't configured yet."
        lines = [f"[score={r['score']:.2f}] {r['text']}" for r in results]
        return "\n".join(lines)

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "save_social_skill",
                "description": (
                    "Save one of the user's own social-media reference files into long-term memory: their "
                    "writing style/voice guide, niche expertise, content pillars, or examples of past posts "
                    "that worked. Call this when the user shares this kind of material (e.g. pastes a skill "
                    "md file), so future post/video ideas are grounded in what they actually know and sound "
                    "like — never in generic or invented expertise. One call per distinct file/topic."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short descriptive title, e.g. 'X writing voice'"},
                        "content": {"type": "string", "description": "The full text/content of the skill file"},
                        "platform": {
                            "type": "string",
                            "description": "Optional: 'x', 'instagram', or omit if it applies generally",
                        },
                    },
                    "required": ["title", "content"],
                },
            },
        },
        save_social_skill,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_social_skills",
                "description": "List the titles of all saved social-media skill/reference files, with a short preview of each.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        list_social_skills,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "recall_social_skills",
                "description": (
                    "Meaning-based search over ONLY the user's saved social-media skill/reference files (not "
                    "general facts or conversation history). Always call this before proposing X or Instagram "
                    "post/video ideas, so ideas are grounded in the user's real expertise, voice, and past "
                    "material rather than something generic or made up."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        recall_social_skills,
    )
