import pytest

from edith.memory import db, ideas_bugs_store


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_create_and_get(conn):
    item_id = ideas_bugs_store.create_idea_bug(conn, "idea", "Ship a globe view", note="later", project="Monitor")
    item = ideas_bugs_store.get_idea_bug(conn, item_id)
    assert item["kind"] == "idea"
    assert item["title"] == "Ship a globe view"
    assert item["note"] == "later"
    assert item["project"] == "Monitor"
    assert item["status"] == "open"


def test_list_filters_by_kind_and_status(conn):
    ideas_bugs_store.create_idea_bug(conn, "idea", "Idea one")
    bug_id = ideas_bugs_store.create_idea_bug(conn, "bug", "Bug one")
    ideas_bugs_store.resolve_idea_bug(conn, bug_id)

    assert len(ideas_bugs_store.list_ideas_bugs(conn)) == 2
    assert len(ideas_bugs_store.list_ideas_bugs(conn, kind="idea")) == 1
    assert len(ideas_bugs_store.list_ideas_bugs(conn, status="open")) == 1
    assert len(ideas_bugs_store.list_ideas_bugs(conn, status="resolved")) == 1


def test_resolve_sets_status_and_timestamp(conn):
    item_id = ideas_bugs_store.create_idea_bug(conn, "bug", "Crashes on save")
    assert ideas_bugs_store.resolve_idea_bug(conn, item_id) is True
    item = ideas_bugs_store.get_idea_bug(conn, item_id)
    assert item["status"] == "resolved"
    assert item["resolved_at"] is not None


def test_resolve_unknown_id_returns_false(conn):
    assert ideas_bugs_store.resolve_idea_bug(conn, 999) is False


def test_delete(conn):
    item_id = ideas_bugs_store.create_idea_bug(conn, "idea", "Delete me")
    assert ideas_bugs_store.delete_idea_bug(conn, item_id) is True
    assert ideas_bugs_store.get_idea_bug(conn, item_id) is None
