import pytest

from edith.memory.records import planning, system
from edith.plugins.career import store as career
from edith.memory.storage import sqlite


@pytest.fixture
def conn(tmp_path):
    c = sqlite.connect(tmp_path / "test.db")
    yield c
    c.close()


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------

def _conn(tmp_path):
    return sqlite.connect(tmp_path / "test.db")


def test_create_and_get_goal(tmp_path):
    conn = _conn(tmp_path)
    goal_id = planning.create_goal(conn, "Ship v2", "Get the dashboard out", "2026-08-01")

    goal = planning.get_goal(conn, goal_id)

    assert goal["title"] == "Ship v2"
    assert goal["description"] == "Get the dashboard out"
    assert goal["target_date"] == "2026-08-01"
    assert goal["status"] == "active"
    assert goal["milestones"] == []


def test_get_goal_missing_returns_none(tmp_path):
    conn = _conn(tmp_path)
    assert planning.get_goal(conn, 999) is None


def test_update_goal_only_changes_given_fields(tmp_path):
    conn = _conn(tmp_path)
    goal_id = planning.create_goal(conn, "Original title", "Original desc")

    ok = planning.update_goal(conn, goal_id, status="done")

    assert ok is True
    goal = planning.get_goal(conn, goal_id)
    assert goal["status"] == "done"
    assert goal["title"] == "Original title"
    assert goal["description"] == "Original desc"


def test_update_goal_no_fields_is_noop(tmp_path):
    conn = _conn(tmp_path)
    goal_id = planning.create_goal(conn, "Title")

    ok = planning.update_goal(conn, goal_id)

    assert ok is False


def test_update_goal_missing_id_returns_false(tmp_path):
    conn = _conn(tmp_path)
    assert planning.update_goal(conn, 999, status="done") is False


def test_list_goals_filters_by_status(tmp_path):
    conn = _conn(tmp_path)
    active_id = planning.create_goal(conn, "Active goal")
    done_id = planning.create_goal(conn, "Done goal")
    planning.update_goal(conn, done_id, status="done")

    active_goals = planning.list_goals(conn, status="active")

    assert len(active_goals) == 1
    assert active_goals[0]["id"] == active_id


def test_delete_goal_removes_goal_and_milestones(tmp_path):
    conn = _conn(tmp_path)
    goal_id = planning.create_goal(conn, "Temp goal")
    planning.add_milestone(conn, goal_id, "step 1")

    ok = planning.delete_goal(conn, goal_id)

    assert ok is True
    assert planning.get_goal(conn, goal_id) is None
    assert conn.execute("SELECT * FROM goal_milestones WHERE goal_id = ?", (goal_id,)).fetchall() == []


def test_milestones_ordered_by_sort_order(tmp_path):
    conn = _conn(tmp_path)
    goal_id = planning.create_goal(conn, "Goal with steps")
    planning.add_milestone(conn, goal_id, "first")
    planning.add_milestone(conn, goal_id, "second")
    planning.add_milestone(conn, goal_id, "third")

    milestones = planning.list_milestones(conn, goal_id)

    assert [m["title"] for m in milestones] == ["first", "second", "third"]
    assert [m["sort_order"] for m in milestones] == [0, 1, 2]


def test_set_milestone_done_and_undone(tmp_path):
    conn = _conn(tmp_path)
    goal_id = planning.create_goal(conn, "Goal")
    milestone_id = planning.add_milestone(conn, goal_id, "step")

    assert planning.set_milestone_done(conn, milestone_id, True) is True
    milestone = planning.list_milestones(conn, goal_id)[0]
    assert milestone["done"] == 1
    assert milestone["done_at"] is not None

    planning.set_milestone_done(conn, milestone_id, False)
    milestone = planning.list_milestones(conn, goal_id)[0]
    assert milestone["done"] == 0
    assert milestone["done_at"] is None


def test_set_milestone_done_missing_id_returns_false(tmp_path):
    conn = _conn(tmp_path)
    assert planning.set_milestone_done(conn, 999, True) is False


def test_get_goal_includes_milestones(tmp_path):
    conn = _conn(tmp_path)
    goal_id = planning.create_goal(conn, "Goal")
    planning.add_milestone(conn, goal_id, "step 1")
    planning.add_milestone(conn, goal_id, "step 2")

    goal = planning.get_goal(conn, goal_id)

    assert len(goal["milestones"]) == 2


def test_add_and_list_insights_unseen_only(tmp_path):
    conn = _conn(tmp_path)
    planning.add_insight(conn, "First insight")
    seen_id = planning.add_insight(conn, "Second insight")
    planning.dismiss_insight(conn, seen_id)

    unseen = planning.list_insights(conn, unseen_only=True)
    all_insights = planning.list_insights(conn, unseen_only=False)

    assert len(unseen) == 1
    assert unseen[0]["title"] == "First insight"
    assert len(all_insights) == 2


def test_dismiss_insight_idempotent(tmp_path):
    conn = _conn(tmp_path)
    insight_id = planning.add_insight(conn, "Some insight")

    assert planning.dismiss_insight(conn, insight_id) is True
    assert planning.dismiss_insight(conn, insight_id) is False  # already dismissed


def test_insight_can_reference_a_goal(tmp_path):
    conn = _conn(tmp_path)
    goal_id = planning.create_goal(conn, "Goal")
    planning.add_insight(conn, "Update", kind="goal_update", goal_id=goal_id)

    insights = planning.list_insights(conn)

    assert insights[0]["goal_id"] == goal_id
    assert insights[0]["kind"] == "goal_update"


def test_create_and_get_idea_bug(conn):
    item_id = planning.create_idea_bug(conn, "idea", "Ship a globe view", note="later", project="Monitor")
    item = planning.get_idea_bug(conn, item_id)
    assert item["kind"] == "idea"
    assert item["title"] == "Ship a globe view"
    assert item["note"] == "later"
    assert item["project"] == "Monitor"
    assert item["status"] == "open"


def test_list_filters_by_kind_and_status(conn):
    planning.create_idea_bug(conn, "idea", "Idea one")
    bug_id = planning.create_idea_bug(conn, "bug", "Bug one")
    planning.resolve_idea_bug(conn, bug_id)

    assert len(planning.list_ideas_bugs(conn)) == 2
    assert len(planning.list_ideas_bugs(conn, kind="idea")) == 1
    assert len(planning.list_ideas_bugs(conn, status="open")) == 1
    assert len(planning.list_ideas_bugs(conn, status="resolved")) == 1


def test_resolve_sets_status_and_timestamp(conn):
    item_id = planning.create_idea_bug(conn, "bug", "Crashes on save")
    assert planning.resolve_idea_bug(conn, item_id) is True
    item = planning.get_idea_bug(conn, item_id)
    assert item["status"] == "resolved"
    assert item["resolved_at"] is not None


def test_resolve_unknown_id_returns_false(conn):
    assert planning.resolve_idea_bug(conn, 999) is False


def test_delete(conn):
    item_id = planning.create_idea_bug(conn, "idea", "Delete me")
    assert planning.delete_idea_bug(conn, item_id) is True
    assert planning.get_idea_bug(conn, item_id) is None


# ---------------------------------------------------------------------------
# career
# ---------------------------------------------------------------------------

def test_create_and_get_application(conn):
    app_id = career.create_application(
        conn, "Acme Inc", company_domain="acme.com", role_title="Full Stack Engineer",
        source="a16z", source_url="https://a16z.com/portfolio/", job_posting_url="https://acme.com/jobs/1",
    )
    app = career.get_application(conn, app_id)
    assert app["company"] == "Acme Inc"
    assert app["company_domain"] == "acme.com"
    assert app["status"] == "discovered"
    assert app["channel"] == "undetermined"


def test_find_existing_application_only_matches_in_flight_statuses(conn):
    app_id = career.create_application(conn, "Acme Inc", company_domain="acme.com")
    # a freshly discovered lead already counts as "in flight" — prevents immediately
    # re-recording the same company as a second lead
    found = career.find_existing_application(conn, "acme.com")
    assert found is not None and found["id"] == app_id

    career.update_application(conn, app_id, status="drafted")
    found = career.find_existing_application(conn, "acme.com")
    assert found is not None and found["id"] == app_id

    career.update_application(conn, app_id, status="failed")
    assert career.find_existing_application(conn, "acme.com") is None


def test_update_application_rejects_unknown_field(conn):
    app_id = career.create_application(conn, "Acme Inc")
    with pytest.raises(ValueError):
        career.update_application(conn, app_id, company="Different Co")


def test_list_applications_filters_by_status(conn):
    a = career.create_application(conn, "Acme Inc")
    b = career.create_application(conn, "Beta Inc")
    career.update_application(conn, b, status="sent")

    assert len(career.list_applications(conn)) == 2
    assert len(career.list_applications(conn, status="sent")) == 1
    assert career.list_applications(conn, status="discovered")[0]["id"] == a


def test_count_sent_today(conn):
    a = career.create_application(conn, "Acme Inc")
    assert career.count_sent_today(conn) == 0
    career.update_application(
        conn, a, status="sent", sent_at="2020-01-01T09:00:00.000Z"
    )
    assert career.count_sent_today(conn) == 0  # a stale date shouldn't count as "today"
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    career.update_application(conn, a, sent_at=today)
    assert career.count_sent_today(conn) == 1


def test_resume_text_roundtrip(conn):
    assert career.get_resume_text(conn) is None
    career.save_resume_text(conn, "Alex Doe, Full Stack Engineer...", "resume.pdf")
    assert career.get_resume_text(conn) == "Alex Doe, Full Stack Engineer..."
    career.save_resume_text(conn, "updated text", "resume.pdf")
    assert career.get_resume_text(conn) == "updated text"


def test_style_sample_roundtrip_independent_of_resume(conn):
    career.save_resume_text(conn, "resume text", "resume.pdf")
    assert career.get_style_sample(conn) is None
    career.save_style_sample(conn, "Hi, excited to apply...", "email.txt")
    assert career.get_style_sample(conn) == "Hi, excited to apply..."
    # saving the style sample must not clobber the previously saved resume text
    assert career.get_resume_text(conn) == "resume text"


def test_style_sample_before_resume(conn):
    career.save_style_sample(conn, "sample", "email.txt")
    assert career.get_style_sample(conn) == "sample"
    career.save_resume_text(conn, "resume text", "resume.pdf")
    assert career.get_resume_text(conn) == "resume text"
    assert career.get_style_sample(conn) == "sample"


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------

def test_set_get_delete_setting(conn):
    system.set_setting(conn, "role", "PM", category="identity")
    assert system.get_setting(conn, "role") == "PM"

    system.set_setting(conn, "role", "Senior PM", category="identity")  # upsert
    assert system.get_setting(conn, "role") == "Senior PM"
    assert system.list_settings(conn, "identity") == [{"key": "role", "value": "Senior PM", "category": "identity"}]

    assert system.delete_setting(conn, "role") is True
    assert system.get_setting(conn, "role") is None
    assert system.delete_setting(conn, "role") is False


def test_queue_and_get_pending_actions(conn):
    action_id = system.queue_pending_action(
        conn, tool_name="send_email", args={"to": "x@y.com"}, preview="Send email to x@y.com"
    )
    pending = system.get_pending_actions(conn)
    assert len(pending) == 1
    assert pending[0]["id"] == action_id
    assert pending[0]["tool_name"] == "send_email"
    assert pending[0]["args"] == {"to": "x@y.com"}
    assert pending[0]["status"] == "pending"


def test_resolve_pending_action_approved(conn):
    action_id = system.queue_pending_action(conn, "send_email", {"to": "x@y.com"}, "preview")
    resolved = system.resolve_pending_action(conn, action_id, "approved")
    assert resolved["tool_name"] == "send_email"
    assert resolved["args"] == {"to": "x@y.com"}
    assert system.get_pending_actions(conn, status="pending") == []
    assert len(system.get_pending_actions(conn, status="approved")) == 1


def test_list_settings_by_category(conn):
    system.set_setting(conn, "https://a.example", "site A", category="tracked_url")
    system.set_setting(conn, "https://b.example", "site B", category="tracked_url")
    system.set_setting(conn, "role", "PM", category="identity")

    tracked = system.list_settings(conn, "tracked_url")
    assert {f["key"] for f in tracked} == {"https://a.example", "https://b.example"}
    assert system.list_settings(conn, "nonexistent") == []


def test_resolve_pending_action_already_resolved_returns_none(conn):
    action_id = system.queue_pending_action(conn, "send_email", {}, "preview")
    system.resolve_pending_action(conn, action_id, "rejected")
    assert system.resolve_pending_action(conn, action_id, "approved") is None


def test_resolve_pending_action_unknown_id_returns_none(conn):
    assert system.resolve_pending_action(conn, 9999, "approved") is None
