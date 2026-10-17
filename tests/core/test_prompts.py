from edith.prompts import build_system_prompt


def _note(context, region, id=1):
    return {"id": id, "context": context, "region": region, "created_at": "2026-10-17T00:00:00Z"}


def test_core_memories_are_grouped_by_region():
    core = [_note("Works as a PM at Allore.", "career"), _note("Wants concise answers.", "preferences", 2)]
    prompt = build_system_prompt(core)

    section = prompt.split("## What you know about the user (core memories, by region)")[1].split("##")[0]
    assert "- career:\n  - Works as a PM at Allore." in section
    assert "- preferences:\n  - Wants concise answers." in section


def test_recalled_memories_render_with_ids():
    recalled = [{**_note("Training for a half marathon.", "health", 7), "score": 0.81}]
    prompt = build_system_prompt([], memories=recalled)
    assert "#7 [health, 2026-10-17, match 0.81] Training for a half marathon." in prompt


def test_active_structured_goals_appear_in_goals_section():
    goals = [
        {"title": "Switch into ML engineering", "status": "active", "target_date": "2026-12-31", "milestones": [{"done": True}, {"done": False}]},
        {"title": "Dropped goal", "status": "dropped", "target_date": None, "milestones": []},
    ]
    prompt = build_system_prompt([], goals)
    goals_section = prompt.split("## What you know about the user")[0]
    assert "Switch into ML engineering (1/2 milestones) — due 2026-12-31" in goals_section
    assert "Dropped goal" not in goals_section


def test_empty_sections_render_placeholder_text():
    prompt = build_system_prompt([])
    assert "(Nothing set yet.)" in prompt
    assert "(Nothing yet — you're just getting to know them.)" in prompt
    assert "(None recalled for this message.)" in prompt
