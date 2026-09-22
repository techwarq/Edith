from edith.memory import db
from edith.tools.productivity import goals as goals_tool
from edith.tools.registry import ToolRegistry


def _registry(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    r = ToolRegistry()
    goals_tool.register(r, conn)
    return r, conn


def test_create_goal_tool(tmp_path):
    r, conn = _registry(tmp_path)

    result = r.dispatch("create_goal", {"title": "Learn ML", "description": "", "target_date": ""})

    assert "Created goal #1" in result
    assert "Learn ML" in result


def test_update_goal_status_rejects_invalid_status(tmp_path):
    r, conn = _registry(tmp_path)
    r.dispatch("create_goal", {"title": "Goal", "description": "", "target_date": ""})

    result = r.dispatch("update_goal_status", {"goal_id": 1, "status": "bogus"})

    assert result.startswith("ERROR")


def test_update_goal_status_success(tmp_path):
    r, conn = _registry(tmp_path)
    r.dispatch("create_goal", {"title": "Goal", "description": "", "target_date": ""})

    result = r.dispatch("update_goal_status", {"goal_id": 1, "status": "done"})

    assert "marked done" in result


def test_update_goal_status_missing_goal(tmp_path):
    r, conn = _registry(tmp_path)

    result = r.dispatch("update_goal_status", {"goal_id": 999, "status": "done"})

    assert "No goal with id 999" in result


def test_list_goals_empty(tmp_path):
    r, conn = _registry(tmp_path)

    result = r.dispatch("list_goals", {"status": ""})

    assert "No goals tracked yet." == result


def test_list_goals_shows_milestone_progress(tmp_path):
    r, conn = _registry(tmp_path)
    r.dispatch("create_goal", {"title": "Ship it", "description": "", "target_date": "2026-09-01"})
    r.dispatch("add_milestone", {"goal_id": 1, "title": "step 1", "target_date": ""})
    r.dispatch("complete_milestone", {"milestone_id": 1})
    r.dispatch("add_milestone", {"goal_id": 1, "title": "step 2", "target_date": ""})

    result = r.dispatch("list_goals", {"status": ""})

    assert "#1 [active] Ship it (1/2 milestones) — due 2026-09-01" in result


def test_add_milestone_to_missing_goal(tmp_path):
    r, conn = _registry(tmp_path)

    result = r.dispatch("add_milestone", {"goal_id": 999, "title": "step", "target_date": ""})

    assert result.startswith("ERROR")


def test_complete_milestone_missing(tmp_path):
    r, conn = _registry(tmp_path)

    result = r.dispatch("complete_milestone", {"milestone_id": 999})

    assert "No milestone with id 999" in result


def test_surface_insight_defaults_and_invalid_kind_falls_back(tmp_path):
    r, conn = _registry(tmp_path)

    result = r.dispatch("surface_insight", {"title": "Noticed a pattern", "body": "", "kind": "bogus", "goal_id": 0})

    assert "Queued insight #1" in result
    row = conn.execute("SELECT * FROM insights WHERE id = 1").fetchone()
    assert row["kind"] == "insight"
    assert row["goal_id"] is None


def test_surface_insight_links_goal(tmp_path):
    r, conn = _registry(tmp_path)
    r.dispatch("create_goal", {"title": "Goal", "description": "", "target_date": ""})

    r.dispatch("surface_insight", {"title": "Update", "body": "progress", "kind": "goal_update", "goal_id": 1})

    row = conn.execute("SELECT * FROM insights WHERE id = 1").fetchone()
    assert row["goal_id"] == 1
    assert row["kind"] == "goal_update"
