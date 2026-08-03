import pytest

from edith.memory import db, store
from edith.tools import projects
from edith.tools.registry import ToolRegistry


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def _registry(conn):
    r = ToolRegistry()
    projects.register(r, conn)
    return r


def test_track_project_saves_and_lists(conn):
    r = _registry(conn)
    r.dispatch("track_project", {"name": "edith", "description": "building the memory layer"})

    result = r.dispatch("list_projects", {})

    assert result == "edith: building the memory layer"


def test_track_project_defaults_description_to_name(conn):
    r = _registry(conn)
    r.dispatch("track_project", {"name": "edith"})

    assert store.get_fact(conn, "edith") == "edith"


def test_track_project_again_updates_not_duplicates(conn):
    r = _registry(conn)
    r.dispatch("track_project", {"name": "edith", "description": "starting out"})
    r.dispatch("track_project", {"name": "edith", "description": "shipping voice mode"})

    facts = store.get_facts_by_category(conn, projects.WORKING_ON_CATEGORY)
    assert len(facts) == 1
    assert facts[0]["value"] == "shipping voice mode"


def test_untrack_project(conn):
    r = _registry(conn)
    r.dispatch("track_project", {"name": "edith"})

    result = r.dispatch("untrack_project", {"name": "edith"})

    assert result == "Removed 'edith' from what you're working on."
    assert r.dispatch("list_projects", {}) == "Nothing tracked yet."


def test_untrack_project_not_tracked(conn):
    r = _registry(conn)
    result = r.dispatch("untrack_project", {"name": "nope"})
    assert result == "'nope' wasn't tracked."


def test_list_projects_empty(conn):
    r = _registry(conn)
    assert r.dispatch("list_projects", {}) == "Nothing tracked yet."
