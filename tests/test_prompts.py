from edith.prompts import build_system_prompt


def test_behavior_facts_go_in_dedicated_section():
    facts = [
        {"key": "current_role", "value": "PM at Allore", "category": "identity"},
        {"key": "tone_pref", "value": "be concise, no fluff", "category": "behavior"},
    ]
    prompt = build_system_prompt(facts)

    goals_section, profile_section = prompt.split("## What you know about the user so far")
    assert "tone_pref: be concise, no fluff" in goals_section
    assert "current_role: PM at Allore" not in goals_section
    assert "current_role: PM at Allore" in profile_section


def test_category_goal_facts_now_go_in_profile_section_not_goals():
    # Real goals live in the structured goals table (create_goal) now, surfaced
    # via the `goals` param below — category="goal" on save_fact is legacy/
    # discouraged, so any stray fact still tagged that way just falls through
    # to the generic profile section rather than being dropped or duplicated.
    facts = [{"key": "old_style_goal", "value": "switch into ML engineering", "category": "goal"}]
    prompt = build_system_prompt(facts)
    assert "old_style_goal: switch into ML engineering" in prompt.split("## What you know about the user so far")[1]


def test_active_structured_goals_appear_in_goals_section():
    goals = [
        {"title": "Switch into ML engineering", "status": "active", "target_date": "2026-12-31", "milestones": [{"done": True}, {"done": False}]},
        {"title": "Dropped goal", "status": "dropped", "target_date": None, "milestones": []},
    ]
    prompt = build_system_prompt([], goals)
    goals_section = prompt.split("## What you know about the user so far")[0]
    assert "Switch into ML engineering (1/2 milestones) — due 2026-12-31" in goals_section
    assert "Dropped goal" not in goals_section


def test_empty_sections_render_placeholder_text():
    prompt = build_system_prompt([])
    assert "(Nothing set yet.)" in prompt
    assert "(No facts learned yet.)" in prompt


def test_facts_without_category_go_in_profile_section():
    facts = [{"key": "favorite_color", "value": "blue", "category": None}]
    prompt = build_system_prompt(facts)
    assert "favorite_color: blue" in prompt.split("## What you know about the user so far")[1]
