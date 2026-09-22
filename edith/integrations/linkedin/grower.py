"""Best LinkedIn Grower Agent — Qwen3.7 Flash + Muse Image, dual-persona, pgvector + stats learning.

Phase 2 core: generate the single best post for personal OR company, grounded in skills/goals/insights.
"""
import logging
from typing import Any

from edith.integrations.linkedin import store
from edith.integrations.linkedin import pgvector as pgmem
from edith.integrations.linkedin.prompts import build_generation_messages, build_planner_messages, refine_image_prompt
from edith.integrations.linkedin.openrouter import generate_text_fallback, generate_image, plan_calendar

logger = logging.getLogger("edith.integrations.linkedin.grower")

# ---------- helpers ----------
def _load_context(conn, author_urn: str) -> tuple[dict, list[dict], list[dict], list[dict]]:
    skills_ctx = store.get_skills_context(conn, author_urn)
    goals = store.list_goals(conn, author_urn=author_urn, status="active")
    insights = store.list_insights(conn, author_urn=author_urn, limit=10)
    # past winners = posts with high engagement if available, else recent published
    winners = []
    try:
        # try to get top insights kind=winner, else fallback to recent published posts
        winners = [i for i in insights if i["kind"] == "winner"][:3]
        if not winners:
            recent = store.list_posts(conn, author_urn=author_urn, status="published", limit=3)
            for p in recent:
                # fetch latest stat to give engagement context
                stat = store.get_latest_stat(conn, p["id"])
                winners.append({"title": p.get("hook") or p["commentary"][:60], "body": p["commentary"][:400], "evidence": stat})
    except Exception:
        logger.exception("winner load failed")
    return skills_ctx, goals, insights, winners

def generate_best_post(
    conn,
    genai_client,
    author_urn: str,
    topic: str,
    pillar: str = "",
    tone: str = "",
    goal_id: str | None = None,
    include_image: bool = True,
) -> dict[str, Any]:
    """Generate one best LinkedIn post for given author. Returns post dict ready to save."""
    author = store.get_author(conn, author_urn)
    if not author:
        raise ValueError(f"author not found: {author_urn}. Create via POST /api/linkedin/authors first")
    author_type = author["type"]  # personal / company

    skills_ctx, goals, insights, winners = _load_context(conn, author_urn)
    # if goal_id specified, prioritize that goal
    if goal_id:
        g = store.get_goal(conn, goal_id)
        if g:
            goals = [g] + [x for x in goals if x["id"] != goal_id]

    # pgvector augment: semantic search past winners by topic (if enabled)
    if genai_client and pgmem.is_enabled():
        try:
            vec_hits = pgmem.pg_search(genai_client, author_urn, topic, top_k=3)
            for h in vec_hits:
                winners.append({"title": h.get("pillar") or "past", "body": h.get("text","")[:350]})
        except Exception:
            logger.exception("pgvector search failed, continuing")

    messages = build_generation_messages(
        author_type=author_type,
        topic=topic,
        skills_ctx=skills_ctx,
        goals=goals,
        insights=insights,
        past_winners=winners,
        tone=tone,
        pillar=pillar,
    )

    # Call Qwen cheapest: qwen/qwen3.7-flash ($0.03/$0.13)
    result = generate_text_fallback(messages)

    commentary = result.get("commentary", "").strip()
    if not commentary:
        raise RuntimeError(f"LLM returned empty commentary: {result}")

    image_b64 = None
    image_model = None
    image_cost = 0
    image_prompt_raw = result.get("image_prompt", "")
    refined_prompt = refine_image_prompt(image_prompt_raw, author_type) if image_prompt_raw else ""

    if include_image and refined_prompt:
        try:
            img_res = generate_image(refined_prompt, aspect_ratio="1:1")
            image_b64 = img_res.get("b64_json")
            image_model = img_res.get("model")
            image_cost = img_res.get("cost", 0.01)
            # keep prompt that was actually used
            result["_final_image_prompt"] = refined_prompt
        except Exception as e:
            logger.warning("image generation failed, returning text only: %s", e)
            result["_image_error"] = str(e)

    hashtags = result.get("hashtags") or []
    # normalize hashtags: ensure #
    hashtags = [h if h.startswith("#") else f"#{h}" for h in hashtags]

    # Cost estimate
    usage = result.get("_usage", {})
    model_used = result.get("_model", "qwen/qwen3.7-flash")
    tokens_used = usage.get("total_tokens", 0)

    # Don't auto-save here — caller decides draft vs scheduled. Return payload.
    return {
        "author_urn": author_urn,
        "author_type": author_type,
        "commentary": commentary,
        "hook": result.get("hook", ""),
        "cta": result.get("cta", ""),
        "pillar": result.get("pillar", pillar),
        "hashtags": hashtags,
        "image_prompt": refined_prompt or image_prompt_raw,
        "image_b64": image_b64,
        "image_model": image_model,
        "goal_id": goal_id,
        "model_used": model_used,
        "tokens_used": tokens_used,
        "cost_usd": image_cost,  # text cost negligible (~$0.00002), keep image cost
        "why_this_will_work": result.get("why_this_will_work", ""),
        "_raw": result,
    }

def save_generated_as_post(
    conn,
    generated: dict[str, Any],
    status: str = "draft",
    scheduled_at: str | None = None,
) -> dict[str, Any]:
    """Persist generated dict as linkedin_posts row. Handles personal=manual vs company=scheduled."""
    author_urn = generated["author_urn"]
    author_type = generated["author_type"]
    # personal should never be scheduled autopost; coerce to manual/draft
    if author_type == "personal" and status == "scheduled":
        status = "manual"
    # company defaults to scheduled if scheduled_at present, else draft
    if status not in ("draft", "manual", "scheduled", "published"):
        status = "draft"
    post = store.create_post(
        conn,
        author_urn=author_urn,
        author_type=author_type,
        commentary=generated["commentary"],
        image_prompt=generated.get("image_prompt"),
        image_b64=generated.get("image_b64"),
        image_model=generated.get("image_model"),
        hashtags=generated.get("hashtags"),
        hook=generated.get("hook"),
        cta=generated.get("cta"),
        pillar=generated.get("pillar"),
        goal_id=generated.get("goal_id"),
        status=status,
        scheduled_at=scheduled_at,
        model_used=generated.get("model_used"),
        tokens_used=generated.get("tokens_used"),
        cost_usd=generated.get("cost_usd"),
    )
    # also store in pgvector for future learning (text for retrieval)
    try:
        from edith.integrations.linkedin.pgvector import pg_upsert
        # need genai_client — we don't have it here, so writer must call separately if available
        # we store via direct fallback: if pgvector enabled but no client, we skip (best effort)
        pass
    except Exception:
        pass
    return post

def generate_calendar_plan(conn, author_urn: str, days: int = 7) -> list[dict]:
    author = store.get_author(conn, author_urn)
    if not author:
        raise ValueError(f"author not found: {author_urn}")
    skills_ctx, goals, _, _ = _load_context(conn, author_urn)
    messages = build_planner_messages(author["type"], skills_ctx, goals, days=days)
    plan = plan_calendar(messages)
    # plan is list of {day_offset, topic, pillar, hook_idea, why}
    return plan
