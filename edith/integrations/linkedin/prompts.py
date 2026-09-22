"""Prompts for the best LinkedIn grower agent.

Encodes 2026 virality playbook: hooks, skyscraper value, dwell time, comment bait.
Dual persona support: personal (founder/story, manual) vs company (authority/product, autopost).
"""
from textwrap import dedent

# ---------- Author voice templates ----------
PERSONA_VOICES = {
    "personal": dedent("""
        Voice: Founder / operator, first-person, vulnerable + sharp. You teach via stories, not slogans.
        Constraints: never corporate jargon, never AI-sounding listicle. 1-2 line paragraphs, white space.
        You write for humans scrolling at 8am, not investors.
    """),
    "company": dedent("""
        Voice: Company page = authority + value. Third-person or "We", crisp, insight-dense.
        Constraints: no founder diary, no "excited to announce". Teach the market, show proof, invite.
        Every post must make the reader smarter in 45 seconds.
    """),
}

# ---------- Growth pillars that win on LinkedIn late-2026 ----------
GROWTH_PILLARS = [
    "build-in-public (metrics, failures, decisions)",
    "contrarian take (myth busting with proof)",
    "playbook / how-to (stealable framework)",
    "customer story / case study (before/after + numbers)",
    "hiring / culture (attract talent)",
    "vision / market shift (why now)",
    "tooling / behind-the-scenes (stack, workflow)",
]

HOOK_FORMULAS = dedent("""
    HOOKS THAT STOP SCROLL (first 210 chars = above fold, decide everything):
    1. Brutal truth: "I wasted $40k doing {thing} the wrong way."
    2. Counter-intuitive: "Posting daily killed our reach. This grew it 4x:"
    3. Specific result: "How we got 12 inbound leads in 9 days without ads:"
    4. Vulnerability: "We almost shut down last month."
    5. Curiosity gap: "The one LinkedIn metric nobody tracks (but should):"
    6. List with stakes: "5 hiring mistakes cost us 3 great engineers:"
    Never start with question + never "In today's fast-paced world..." + never emoji in first line.
""")

POST_STRUCTURE = dedent("""
    STRUCTURE (2026 LinkedIn algorithm dwells on time + comments):
    - Line 1-2: HOOK (punchy, specific, 7-12 words)
    - Line 3: white space
    - Lines 4-6: RE-HOOK / stakes ("Here's what actually happened:")
    - Body: story or 3-5 bullets with numbers, names, mistakes. Short lines. No jargon. One idea per line.
    - Turn: insight ("The lesson: ...") — make reader feel smart
    - CTA: one soft question that invites story in comments ("What's your version of this?") — never "thoughts?" / "DM me"
    - 3-5 hashtags max, niche not generic (#B2BSaaS not #Business)
    - Length 900-1300 chars ideal (not 3000). Line breaks every 1-2 lines.
""")

# ---------- Main generate prompt ----------
LINKEDIN_GROWER_SYSTEM = dedent("""
    You are the world's best LinkedIn ghostwriter + growth strategist for 2026.
    You write posts that get saved, shared, and commented — not just liked.

    Rules that are non-negotiable:
    - No AI filler ("delve", "unlock", "embark", "tapestry", "leverage").
    - No fake stats. If you don't have a number from context, don't invent one.
    - Specific > generic. Name tools, amounts, days, mistakes.
    - One post = one pillar, one lesson, one CTA.
    - Personal posts: story-first, vulnerable, first-person.
    - Company posts: authority-first, proof-backed, "we" or third-person.
    - Always return valid JSON.

    {hook_formulas}
    {post_structure}
""").format(hook_formulas=HOOK_FORMULAS, post_structure=POST_STRUCTURE)

def build_generation_messages(
    author_type: str,
    topic: str,
    skills_ctx: dict,
    goals: list[dict],
    insights: list[dict],
    past_winners: list[dict],
    tone: str = "",
    pillar: str = "",
) -> list[dict]:
    """Build messages for Qwen call. Returns OpenAI-style messages."""
    voice = PERSONA_VOICES.get(author_type, PERSONA_VOICES["personal"])
    if tone:
        voice += f"\nOverride tone: {tone}"

    # Collect skills as compact context
    skills_lines = []
    for cat, items in skills_ctx.items():
        for it in items:
            skills_lines.append(f"- [{cat}] {it['title']}: {it['content'][:300]}")
    skills_block = "\n".join(skills_lines) if skills_lines else "(no saved skills yet — ask user to add voice/pillars/audience)"

    goals_block = "\n".join(
        f"- {g['title']}: {g['description'] or ''} (target: {g.get('target_value','')}, pillars: {', '.join(g.get('pillars',[]))})"
        for g in goals
    ) or "(no goals set)"

    insights_block = ""
    if insights:
        insights_block = "\n".join(f"- {ins['title']}: {ins['body'][:200]}" for ins in insights[:5])
    else:
        insights_block = "(no learnings yet)"

    winners_block = ""
    if past_winners:
        winners_block = "\n".join(f"- {w.get('title','post')}: {w.get('body','')[:250]}" for w in past_winners[:3])
    else:
        winners_block = "(no past winners yet)"

    pillar_hint = f"Must use pillar: {pillar}" if pillar else f"Pick best pillar from: {', '.join(GROWTH_PILLARS)}"

    user_content = dedent(f"""
        AUTHOR TYPE: {author_type.upper()}
        VOICE: {voice}

        TOPIC / BRIEF: {topic}

        {pillar_hint}

        GOALS (what we optimize for):
        {goals_block}

        SKILLS / VOICE / AUDIENCE / OFFER / PROOF:
        {skills_block}

        LEARNINGS FROM PAST POSTS (what worked/didn't):
        {insights_block}

        WINNERS TO EMULATE (style/length):
        {winners_block}

        TASK: Write ONE LinkedIn post.

        Return JSON with exactly:
        {{
          "hook": "first line only, 7-12 words, stops scroll",
          "commentary": "full post text 900-1300 chars, with line breaks, ready to paste. Must include hook as first line. No markdown bold/italics. Use unicode if needed. End with soft question CTA.",
          "pillar": "one of the 7 pillars",
          "cta": "the question you used",
          "hashtags": ["#tag1","#tag2","#tag3"],
          "image_prompt": "vivid 1-2 sentence prompt for image model, editorial, no text in image, aspect 1:1 friendly, on-brand with topic. No words in image.",
          "why_this_will_work": "1 sentence"
        }}
    """)

    return [
        {"role": "system", "content": LINKEDIN_GROWER_SYSTEM},
        {"role": "user", "content": user_content},
    ]

# ---------- Image prompt refinement ----------
IMAGE_STYLE_PRESETS = {
    "personal": "editorial photo, natural light, candid founder moment, warm tones, shallow depth, no text overlay",
    "company": "clean editorial illustration, minimal, premium, muted palette, abstract product metaphor, no text, no humans stacked",
}

def refine_image_prompt(base_prompt: str, author_type: str) -> str:
    preset = IMAGE_STYLE_PRESETS.get(author_type, IMAGE_STYLE_PRESETS["company"])
    return f"{base_prompt}, {preset}, high detail, 4k, aspect 1:1"

# ---------- Batch planner prompt (content calendar) ----------
PLANNER_SYSTEM = dedent("""
    You are a LinkedIn content calendar planner. Given goals/pillars, you design 7-14 day posting plans that balance pillars,
    avoid repetition, alternate hooks, and build narrative arcs (tease → teach → prove → invite).
    Return JSON array of {day_offset, topic, pillar, hook_idea, why}.
""")

def build_planner_messages(author_type: str, skills_ctx: dict, goals: list[dict], days: int = 7) -> list[dict]:
    skills_lines = []
    for cat, items in skills_ctx.items():
        for it in items:
            skills_lines.append(f"- {cat}: {it['title']}")
    skills_block = "\n".join(skills_lines) or "(no skills)"
    goals_block = "\n".join(f"- {g['title']} ({', '.join(g.get('pillars',[]))})" for g in goals) or "(no goals)"
    return [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": f"AUTHOR TYPE: {author_type}\nGOALS:\n{goals_block}\nSKILLS:\n{skills_block}\nCreate a {days}-day plan. One post per day. Mix pillars. No repeats within 3 days. Hook idea per day. Return JSON array."},
    ]
