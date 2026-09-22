"""Daily viral queue — every day, what to post (LinkedIn + X, educational + apps).

Mix (5 slots, mirrors the shengkunye/MonidHQ/arlanr playbooks saved as x:viral-refs):
  1. linkedin_edu    — teach the technique behind a shipped commit (playbook/contrarian)
  2. linkedin_app    — app outcome: metric + story + ask (MonidHQ style)
  3. x_edu           — one-liner + code/analogy, lowercase (arlanr style)
  4. x_app           — demo/screenshot + ask (shengkunye launch style)
  5. x_build          — build-in-public grind/hiring/learning (arlanr style)

Source material = GitHub digest (techwarq repos) + per-author skills/goals.
Saves each as linkedin_posts draft/manual with pillar=daily + slot name.
"""
import json
import logging
from datetime import datetime, timezone
from textwrap import dedent

from edith.integrations.linkedin import store as lstore
from edith.integrations.linkedin.github_digest import build_digest
from edith.integrations.linkedin.openrouter import generate_text_fallback

logger = logging.getLogger("edith.integrations.linkedin.daily")

SLOTS = [
    {
        "slot": "linkedin_edu",
        "platform": "linkedin",
        "kind": "educational",
        "brief": "LinkedIn educational post (900-1300 chars). Teach ONE technique from the shipped commits — the bug, the fix, the tradeoff. Playbook or contrarian pillar. End with a soft question CTA. 3-4 hashtags.",
    },
    {
        "slot": "linkedin_app",
        "platform": "linkedin",
        "kind": "app_promo",
        "brief": "LinkedIn app post (700-1100 chars). Belief sentence -> what shipped -> proof/number -> thank/tag someone -> direct ask (try it / feedback). MonidHQ style. 3 hashtags max.",
    },
    {
        "slot": "x_edu",
        "platform": "x",
        "kind": "educational",
        "brief": "X post (under 240 chars, lowercase ok). One sharp technical insight from the commits — a gotcha, a one-liner lesson, a hot take with specifics. No link in the post itself; link goes in reply. arlanr style.",
    },
    {
        "slot": "x_app",
        "platform": "x",
        "kind": "app_promo",
        "brief": "X launch-style post (under 240 chars). What shipped + who it helps + ask (try it / vote / reply). Milestone + gratitude like shengkunye ProductHunt posts. Mention demo/screenshot to attach.",
    },
    {
        "slot": "x_build",
        "platform": "x",
        "kind": "build_in_public",
        "brief": "X build-in-public post (under 220 chars). Grind, learning, hiring, or honest in-progress note in TeenCode6 lowercase voice. Personal, no hype, no link unless essential.",
    },
]

DAILY_SYSTEM = dedent("""
    You are the daily content planner for techwarq (Sonali Nayak) — goal: go viral for apps + educational tech on LinkedIn and X.
    You write in the proven styles of shengkunye (launch + ask), MonidHQ (belief + metric), arlanr (lowercase contrarian), and TeenCode6 (honest builder).
    Rules: specific > generic (name repos, files, errors, minutes saved). No AI filler words. No invented metrics — if the digest has no numbers, use the story not fake stats. One slot = one idea.
    Return valid JSON only.
""")

def _ctx_block(title: str, body: str) -> str:
    return f"{title}:\n{body}\n" if body.strip() else ""

def build_daily_messages(digest_summary: str, skills_block: str, goals_block: str, viral_block: str, date_str: str) -> list[dict]:
    slot_descs = "\n".join(f"- {s['slot']} ({s['platform']}/{s['kind']}): {s['brief']}" for s in SLOTS)
    user_content = dedent(f"""
        TODAY: {date_str}

        WHAT SHIPPED (GitHub, last 7d — ground every post in this):
        {digest_summary}

        MY VOICE + PILLARS + AUDIENCE:
        {skills_block}

        MY GOALS:
        {goals_block}

        VIRAL REFERENCES (emulate these patterns):
        {viral_block}

        SLOTS TO FILL (exactly these 5):
        {slot_descs}

        Return JSON object with exactly these keys, each value = {{"text": "ready-to-post copy", "hook": "first line", "why": "1 sentence"}}:
        {{"linkedin_edu": ..., "linkedin_app": ..., "x_edu": ..., "x_app": ..., "x_build": ...}}
    """)
    return [
        {"role": "system", "content": DAILY_SYSTEM},
        {"role": "user", "content": user_content},
    ]

def _blocks_for_author(conn, author_urn: str) -> tuple[str, str, str]:
    skills_ctx = lstore.get_skills_context(conn, author_urn)
    skill_lines = []
    for cat, items in skills_ctx.items():
        for it in items:
            skill_lines.append(f"- [{cat}] {it['title']}: {it['content'][:280]}")
    # shared viral refs
    for it in lstore.list_skills(conn, "x:viral-refs"):
        skill_lines.append(f"- [viral-{it['category']}] {it['title']}: {it['content'][:280]}")
    skills_block = "\n".join(skill_lines) or "(no skills yet)"
    goals = lstore.list_goals(conn, author_urn=author_urn)
    goals_block = "\n".join(f"- {g['title']}: {g['description'] or ''}" for g in goals) or "(no goals)"
    # viral block = just the refs for emphasis
    viral_lines = [f"- {it['title']}: {it['content'][:300]}" for it in lstore.list_skills(conn, "x:viral-refs")]
    viral_block = "\n".join(viral_lines) or "(no viral refs)"
    return skills_block, goals_block, viral_block

def generate_daily_queue(conn, author_urn_linkedin: str, author_urn_x: str = "x:TeenCode6", since_days: int = 7) -> dict:
    """Generate 5-slot queue, save as drafts, return {date, digest, posts}."""
    # author for saving: use linkedin author for linkedin slots, x author for x slots
    author = lstore.get_author(conn, author_urn_linkedin)
    if not author:
        raise ValueError(f"linkedin author not found: {author_urn_linkedin}")
    x_author = lstore.get_author(conn, author_urn_x)

    digest = build_digest(since_days=since_days)
    skills_block, goals_block, viral_block = _blocks_for_author(conn, author_urn_linkedin)
    # also merge X persona skills
    if x_author:
        x_ctx = lstore.get_skills_context(conn, author_urn_x)
        for cat, items in x_ctx.items():
            for it in items:
                skills_block += f"\n- [x-{cat}] {it['title']}: {it['content'][:280]}"

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    messages = build_daily_messages(digest["summary"], skills_block, goals_block, viral_block, date_str)
    result = generate_text_fallback(messages)

    posts = []
    for slot in SLOTS:
        key = slot["slot"]
        item = result.get(key) or {}
        text = (item.get("text") or "").strip()
        if not text:
            logger.warning("daily slot %s empty, skipping", key)
            continue
        # cap lengths per platform
        if slot["platform"] == "x" and len(text) > 280:
            text = text[:277] + "..."
        if slot["platform"] == "linkedin" and len(text) > 3000:
            text = text[:2997] + "..."
        save_urn = author_urn_x if slot["platform"] == "x" else author_urn_linkedin
        save_type = "personal"  # both manual for now (X has no autopost, linkedin personal manual)
        status = "manual" if slot["platform"] == "x" else "draft"
        post = lstore.create_post(
            conn,
            author_urn=save_urn,
            author_type=save_type,
            commentary=text,
            hook=item.get("hook", text.split("\n")[0][:120]),
            pillar=f"daily:{slot['slot']}",
            status=status,
            model_used=result.get("_model", "qwen/qwen3.7-flash"),
            tokens_used=(result.get("_usage", {}) or {}).get("total_tokens", 0),
        )
        posts.append({
            "slot": key,
            "platform": slot["platform"],
            "kind": slot["kind"],
            "post_id": post["id"],
            "text": text,
            "hook": item.get("hook", ""),
            "why": item.get("why", ""),
            "status": post["status"],
        })

    # record an insight so tomorrow learns
    try:
        lstore.add_insight(
            conn, author_urn_linkedin, "pattern",
            f"Daily queue {date_str}",
            f"Generated {len(posts)}/5 slots from {len(digest['commits'])} commits.",
            evidence={"date": date_str, "commit_count": len(digest["commits"])},
        )
    except Exception:
        logger.exception("daily insight save failed")

    return {
        "date": date_str,
        "digest": digest["summary"],
        "commit_count": len(digest["commits"]),
        "model": result.get("_model"),
        "posts": posts,
    }

WEEK_ARC = [
    {"day": 1, "theme": "The cost of boring work", "angle": "Educational: quantify what repetitive research/data work costs teams (hours, salary burn, errors). Agitate the problem Talo kills. No hard pitch — end with question."},
    {"day": 2, "theme": "Not another AI tool", "angle": "Contrarian: tools give you software to operate; Talo gives you the finished job. You buy the result, not the software. No prompting, no workflows."},
    {"day": 3, "theme": "How it works", "angle": "Playbook: describe task in plain English -> agent researches/browses/verifies -> result delivered, pay for time used. Walk through the /hire chat flow."},
    {"day": 4, "theme": "Proof: 500 companies, $67", "angle": "Case study: 500 US SaaS companies + founders/funding/LinkedIn in 6h42m for $67. Show the pipeline RESEARCH->FILTER->VERIFY->ENRICH. Thank + ask."},
    {"day": 5, "theme": "Proof: 1200 profiles + behind the scenes", "angle": "Case study 2 (1200 ICP profiles, 4h12m, $42) + honest build note: og-image/Twitter card fixes, accent color, chat UI redesign. Build-in-public."},
    {"day": 6, "theme": "Educational teardown", "angle": "Teach one technique from the commits (lead-list building, data dedup/verify pipeline, og-metadata debugging). Pure value, soft Talo mention at most."},
    {"day": 7, "theme": "The ask: waitlist 50% off", "angle": "Launch-style ask (shengkunye playbook): milestone + gratitude + direct CTA. Talo not live yet — waitlist with 50% off at talo.abstraklabs.com. Make it easy to say yes."},
]

WEEK_SYSTEM = dedent("""
    You are the daily content planner for techwarq (Sonali Nayak) — goal: grow the Talo waitlist (talo.abstraklabs.com, AI freelancer $10/hr, 50% off launch offer).
    Styles: shengkunye (milestone + gratitude + ask), MonidHQ (belief + metric), arlanr (lowercase contrarian), TeenCode6 (honest lowercase builder).
    Rules: specific > generic (name repos, hours, dollars, pipelines). No AI filler. No invented metrics — only the proof points given. LinkedIn 900-1300 chars with soft question CTA. X under 240 chars, lowercase ok, no link in post body (link in reply).
    Return valid JSON only.
""")

def build_week_day_messages(date_str: str, day_num: int, theme: str, angle: str, talo_block: str, skills_block: str, goals_block: str, prev_hooks: list[str]) -> list[dict]:
    prev = "\n".join(f"- {h}" for h in prev_hooks) if prev_hooks else "(day 1 — nothing before)"
    user_content = dedent(f"""
        DAY {day_num}/7 — {date_str}. THEME: {theme}
        ANGLE: {angle}

        TALO (ground everything here):
        {talo_block}

        MY VOICE + PROOF:
        {skills_block}

        GOALS:
        {goals_block}

        HOOKS ALREADY USED THIS WEEK (do not repeat):
        {prev}

        Write 3 posts for this day. Return JSON exactly:
        {{
          "linkedin": {{"text": "900-1300 char post, hook first line, soft question CTA, 3-4 hashtags", "hook": "first line", "why": "1 sentence"}},
          "x1": {{"text": "under 240 chars", "hook": "first 40 chars", "why": "1 sentence"}},
          "x2": {{"text": "under 240 chars, different angle from x1 (one promo/one edu or build note)", "hook": "first 40 chars", "why": "1 sentence"}}
        }}
    """)
    return [
        {"role": "system", "content": WEEK_SYSTEM},
        {"role": "user", "content": user_content},
    ]

def generate_week_plan(conn, author_urn_linkedin: str, author_urn_x: str = "x:TeenCode6", start_date: str | None = None) -> dict:
    """7 days x (1 LinkedIn + 2 X). Saves with pillar week:<date>:<slot>, scheduled_at 09:30 UTC."""
    from datetime import timedelta
    author = lstore.get_author(conn, author_urn_linkedin)
    if not author:
        raise ValueError(f"linkedin author not found: {author_urn_linkedin}")
    if start_date:
        base = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        base = datetime.now(timezone.utc) + timedelta(days=1)
        base = base.replace(hour=0, minute=0, second=0, microsecond=0)

    skills_block, goals_block, viral_block = _blocks_for_author(conn, author_urn_linkedin)
    x_ctx = lstore.get_skills_context(conn, author_urn_x)
    for cat, items in x_ctx.items():
        for it in items:
            skills_block += f"\n- [x-{cat}] {it['title']}: {it['content'][:280]}"
    talo_block = skills_block  # skills already include offer/proof/viral refs
    # keep prompt lean: offer+proof first
    days_out = []
    prev_hooks: list[str] = []
    for i, d in enumerate(WEEK_ARC):
        day_date = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        messages = build_week_day_messages(day_date, d["day"], d["theme"], d["angle"], talo_block, skills_block, goals_block, prev_hooks)
        result = generate_text_fallback(messages)
        day_posts = []
        specs = [
            ("linkedin", author_urn_linkedin, "personal", "draft"),
            ("x1", author_urn_x, "personal", "manual"),
            ("x2", author_urn_x, "personal", "manual"),
        ]
        for slot_key, save_urn, save_type, status in specs:
            item = result.get(slot_key) or {}
            text = (item.get("text") or "").strip()
            if not text:
                logger.warning("week day %s slot %s empty", d["day"], slot_key)
                continue
            if slot_key.startswith("x") and len(text) > 280:
                text = text[:277] + "..."
            if slot_key == "linkedin" and len(text) > 3000:
                text = text[:2997] + "..."
            post = lstore.create_post(
                conn,
                author_urn=save_urn,
                author_type=save_type,
                commentary=text,
                hook=item.get("hook", text.split("\n")[0][:120]),
                pillar=f"week:{day_date}:{slot_key}",
                status=status,
                scheduled_at=f"{day_date}T09:30:00Z",
                model_used=result.get("_model", "qwen/qwen3.7-flash"),
                tokens_used=(result.get("_usage", {}) or {}).get("total_tokens", 0),
            )
            hook = item.get("hook", "")
            if hook:
                prev_hooks.append(hook)
            day_posts.append({"slot": slot_key, "post_id": post["id"], "text": text, "hook": hook, "why": item.get("why", ""), "status": status})
        days_out.append({"day": d["day"], "date": day_date, "theme": d["theme"], "posts": day_posts})

    try:
        lstore.add_insight(conn, author_urn_linkedin, "pattern", f"Week plan from {(base).strftime('%Y-%m-%d')}",
            f"7-day Talo growth arc generated ({sum(len(x['posts']) for x in days_out)} posts).",
            evidence={"start": base.strftime("%Y-%m-%d")})
    except Exception:
        logger.exception("week insight save failed")
    return {"start": base.strftime("%Y-%m-%d"), "model": "qwen/qwen3.7-flash", "days": days_out}

def get_week_plan(conn, author_urn_linkedin: str | None = None, start: str | None = None) -> list[dict]:
    """Posts with pillar LIKE 'week:%', grouped by day."""
    q = "SELECT * FROM linkedin_posts WHERE pillar LIKE 'week:%' "
    params: list = []
    if start:
        q += "AND substr(pillar,6,10) >= ? "
        params.append(start)
    if author_urn_linkedin:
        q += "AND (author_urn=? OR author_urn='x:TeenCode6') "
        params.append(author_urn_linkedin)
    q += "ORDER BY substr(pillar,6,10) ASC, created_at ASC"
    rows = conn.execute(q, params).fetchall()
    import json as _json
    days: dict[str, dict] = {}
    for r in rows:
        d = dict(r)
        d["hashtags"] = _json.loads(d["hashtags_json"] or "[]")
        parts = (d.get("pillar") or "").split(":")
        date = parts[1] if len(parts) > 1 else "?"
        slot = parts[2] if len(parts) > 2 else "post"
        d["slot"] = slot
        d["platform"] = "x" if slot.startswith("x") else "linkedin"
        days.setdefault(date, {"date": date, "posts": []})["posts"].append(d)
    return list(days.values())

def get_todays_queue(conn, author_urn_linkedin: str | None = None) -> list[dict]:
    """Posts with pillar LIKE 'daily:%' created today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q = "SELECT * FROM linkedin_posts WHERE pillar LIKE 'daily:%' AND substr(created_at,1,10)=? "
    params: list = [today]
    if author_urn_linkedin:
        # include x posts too (same queue) — match either urn
        q = "SELECT * FROM linkedin_posts WHERE pillar LIKE 'daily:%' AND substr(created_at,1,10)=? AND (author_urn=? OR author_urn='x:TeenCode6') "
        params.append(author_urn_linkedin)
    q += "ORDER BY created_at ASC"
    rows = conn.execute(q, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        import json as _json
        d["hashtags"] = _json.loads(d["hashtags_json"] or "[]")
        # derive slot/platform from pillar daily:<slot>
        slot = (d.get("pillar") or "").split(":", 1)[-1]
        d["slot"] = slot
        d["platform"] = "x" if slot.startswith("x_") else "linkedin"
        out.append(d)
    return out
