"""save_social_skill / list_social_skills / recall_social_skills tools.

Lets Edith act as a social-media (X/Instagram) content assistant grounded in
the user's own material — writing style, niche expertise, content pillars,
past post examples — rather than inventing ideas from nothing. Skill content
is stored as settings with a fixed category ("social_skill"), plus a matching
Qdrant vector under its own type so recall_social_skills can search skill
content specifically without mixing in brain memories.

Content direction ("what I want to post about, my niche, my goals") is
handled separately via the /skill-talk command (edith/commands.py), which
files it in the brain's "content strategy" region — it's the user's stated
intent, not reference material, so it doesn't belong in this same bucket.
"""

from edith.memory.records import system
from edith.memory.storage import qdrant
from edith.tools.base import ToolContext, tool

SOCIAL_SKILL_CATEGORY = "social_skill"
CONTENT_STRATEGY_REGION = "content strategy"


@tool
def save_social_skill(ctx: ToolContext, title: str, content: str, platform: str = "") -> str:
    """Save one of the user's own social-media reference files into long-term memory: their
    writing style/voice guide, niche expertise, content pillars, or examples of past posts
    that worked. Call this when the user shares this kind of material (e.g. pastes a skill
    md file), so future post/video ideas are grounded in what they actually know and sound
    like — never in generic or invented expertise. One call per distinct file/topic.

    Args:
        title: Short descriptive title, e.g. 'X writing voice'
        content: The full text/content of the skill file
        platform: Optional: 'x', 'instagram', or omit if it applies generally
    """
    system.set_setting(ctx.conn, key=title, value=content, category=SOCIAL_SKILL_CATEGORY)
    qdrant.upsert(
        ctx.qdrant_client, ctx.llm_client, SOCIAL_SKILL_CATEGORY, f"{title}: {content}", platform=platform or "general"
    )
    return f"Saved social skill '{title}'."


@tool
def list_social_skills(ctx: ToolContext) -> str:
    """List the titles of all saved social-media skill/reference files, with a short preview of each."""
    facts = system.list_settings(ctx.conn, SOCIAL_SKILL_CATEGORY)
    if not facts:
        return "No social media skill files saved yet."
    lines = []
    for f in facts:
        preview = f["value"] if len(f["value"]) <= 120 else f["value"][:120] + "..."
        lines.append(f"{f['key']} — {preview}")
    return "\n".join(lines)


@tool
def recall_social_skills(ctx: ToolContext, query: str) -> str:
    """Meaning-based search over ONLY the user's saved social-media skill/reference files (not
    general facts or conversation history). Always call this before proposing X or Instagram
    post/video ideas, so ideas are grounded in the user's real expertise, voice, and past
    material rather than something generic or made up.
    """
    results = qdrant.search(ctx.qdrant_client, ctx.llm_client, query, type_filter=SOCIAL_SKILL_CATEGORY)
    if not results:
        return "No matching social skill content found." if ctx.qdrant_client else "Semantic memory isn't configured yet."
    lines = [f"[score={r['score']:.2f}] {r['text']}" for r in results]
    return "\n".join(lines)
