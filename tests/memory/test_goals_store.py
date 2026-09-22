from edith.memory import db, goals_store


def _conn(tmp_path):
    return db.connect(tmp_path / "test.db")


def test_create_and_get_goal(tmp_path):
    conn = _conn(tmp_path)
    goal_id = goals_store.create_goal(conn, "Ship v2", "Get the dashboard out", "2026-08-01")

    goal = goals_store.get_goal(conn, goal_id)

    assert goal["title"] == "Ship v2"
    assert goal["description"] == "Get the dashboard out"
    assert goal["target_date"] == "2026-08-01"
    assert goal["status"] == "active"
    assert goal["milestones"] == []


def test_get_goal_missing_returns_none(tmp_path):
    conn = _conn(tmp_path)
    assert goals_store.get_goal(conn, 999) is None


def test_update_goal_only_changes_given_fields(tmp_path):
    conn = _conn(tmp_path)
    goal_id = goals_store.create_goal(conn, "Original title", "Original desc")

    ok = goals_store.update_goal(conn, goal_id, status="done")

    assert ok is True
    goal = goals_store.get_goal(conn, goal_id)
    assert goal["status"] == "done"
    assert goal["title"] == "Original title"
    assert goal["description"] == "Original desc"


def test_update_goal_no_fields_is_noop(tmp_path):
    conn = _conn(tmp_path)
    goal_id = goals_store.create_goal(conn, "Title")

    ok = goals_store.update_goal(conn, goal_id)

    assert ok is False


def test_update_goal_missing_id_returns_false(tmp_path):
    conn = _conn(tmp_path)
    assert goals_store.update_goal(conn, 999, status="done") is False


def test_list_goals_filters_by_status(tmp_path):
    conn = _conn(tmp_path)
    active_id = goals_store.create_goal(conn, "Active goal")
    done_id = goals_store.create_goal(conn, "Done goal")
    goals_store.update_goal(conn, done_id, status="done")

    active_goals = goals_store.list_goals(conn, status="active")

    assert len(active_goals) == 1
    assert active_goals[0]["id"] == active_id


def test_delete_goal_removes_goal_and_milestones(tmp_path):
    conn = _conn(tmp_path)
    goal_id = goals_store.create_goal(conn, "Temp goal")
    goals_store.add_milestone(conn, goal_id, "step 1")

    ok = goals_store.delete_goal(conn, goal_id)

    assert ok is True
    assert goals_store.get_goal(conn, goal_id) is None
    assert conn.execute("SELECT * FROM goal_milestones WHERE goal_id = ?", (goal_id,)).fetchall() == []


def test_milestones_ordered_by_sort_order(tmp_path):
    conn = _conn(tmp_path)
    goal_id = goals_store.create_goal(conn, "Goal with steps")
    goals_store.add_milestone(conn, goal_id, "first")
    goals_store.add_milestone(conn, goal_id, "second")
    goals_store.add_milestone(conn, goal_id, "third")

    milestones = goals_store.list_milestones(conn, goal_id)

    assert [m["title"] for m in milestones] == ["first", "second", "third"]
    assert [m["sort_order"] for m in milestones] == [0, 1, 2]


def test_set_milestone_done_and_undone(tmp_path):
    conn = _conn(tmp_path)
    goal_id = goals_store.create_goal(conn, "Goal")
    milestone_id = goals_store.add_milestone(conn, goal_id, "step")

    assert goals_store.set_milestone_done(conn, milestone_id, True) is True
    milestone = goals_store.list_milestones(conn, goal_id)[0]
    assert milestone["done"] == 1
    assert milestone["done_at"] is not None

    goals_store.set_milestone_done(conn, milestone_id, False)
    milestone = goals_store.list_milestones(conn, goal_id)[0]
    assert milestone["done"] == 0
    assert milestone["done_at"] is None


def test_set_milestone_done_missing_id_returns_false(tmp_path):
    conn = _conn(tmp_path)
    assert goals_store.set_milestone_done(conn, 999, True) is False


def test_get_goal_includes_milestones(tmp_path):
    conn = _conn(tmp_path)
    goal_id = goals_store.create_goal(conn, "Goal")
    goals_store.add_milestone(conn, goal_id, "step 1")
    goals_store.add_milestone(conn, goal_id, "step 2")

    goal = goals_store.get_goal(conn, goal_id)

    assert len(goal["milestones"]) == 2


def test_add_and_list_insights_unseen_only(tmp_path):
    conn = _conn(tmp_path)
    goals_store.add_insight(conn, "First insight")
    seen_id = goals_store.add_insight(conn, "Second insight")
    goals_store.dismiss_insight(conn, seen_id)

    unseen = goals_store.list_insights(conn, unseen_only=True)
    all_insights = goals_store.list_insights(conn, unseen_only=False)

    assert len(unseen) == 1
    assert unseen[0]["title"] == "First insight"
    assert len(all_insights) == 2


def test_dismiss_insight_idempotent(tmp_path):
    conn = _conn(tmp_path)
    insight_id = goals_store.add_insight(conn, "Some insight")

    assert goals_store.dismiss_insight(conn, insight_id) is True
    assert goals_store.dismiss_insight(conn, insight_id) is False  # already dismissed


def test_insight_can_reference_a_goal(tmp_path):
    conn = _conn(tmp_path)
    goal_id = goals_store.create_goal(conn, "Goal")
    goals_store.add_insight(conn, "Update", kind="goal_update", goal_id=goal_id)

    insights = goals_store.list_insights(conn)

    assert insights[0]["goal_id"] == goal_id
    assert insights[0]["kind"] == "goal_update"
