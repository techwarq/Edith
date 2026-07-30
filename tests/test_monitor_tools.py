import pytest

from edith.memory import db
from edith.tools import monitor
from edith.tools.registry import ToolRegistry


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def registry(conn):
    r = ToolRegistry()
    monitor.register(r, conn)
    return r


def test_log_idea_and_list(registry):
    result = registry.dispatch("log_idea", {"title": "Globe view", "project": "Monitor"})
    assert "Globe view" in result

    listed = registry.dispatch("list_ideas_bugs", {})
    assert "Globe view" in listed
    assert "(idea)" in listed
    assert "[Monitor]" in listed


def test_log_bug_and_resolve(registry):
    registry.dispatch("log_bug", {"title": "Crashes on save"})
    listed = registry.dispatch("list_ideas_bugs", {"kind": "bug"})
    item_id = int(listed.split("#")[1].split(" ")[0])

    resolved = registry.dispatch("resolve_idea_bug", {"item_id": item_id})
    assert "resolved" in resolved
    assert registry.dispatch("list_ideas_bugs", {"status": "open"}) == "Nothing logged yet."


def test_resolve_unknown_id(registry):
    result = registry.dispatch("resolve_idea_bug", {"item_id": 999})
    assert "No idea/bug with id 999" in result


def test_track_list_untrack_shipping_repo(registry):
    result = registry.dispatch("track_shipping_repo", {"repo": "techwarq/edith", "label": "Edith"})
    assert "techwarq/edith" in result

    listed = registry.dispatch("list_shipping_repos", {})
    assert "techwarq/edith (Edith)" in listed

    untracked = registry.dispatch("untrack_shipping_repo", {"repo": "techwarq/edith"})
    assert "Stopped tracking" in untracked
    assert registry.dispatch("list_shipping_repos", {}) == "No repos are being tracked in the shipping log yet."


def test_untrack_unknown_repo(registry):
    result = registry.dispatch("untrack_shipping_repo", {"repo": "never/tracked"})
    assert "wasn't being tracked" in result


def test_track_list_untrack_vercel_project(registry):
    result = registry.dispatch("track_vercel_project", {"project_id": "prj_abc", "label": "Snips"})
    assert "Snips" in result
    assert "prj_abc" in result

    listed = registry.dispatch("list_vercel_projects", {})
    assert "Snips (prj_abc)" in listed

    untracked = registry.dispatch("untrack_vercel_project", {"project_id": "prj_abc"})
    assert "Stopped tracking" in untracked
    assert registry.dispatch("list_vercel_projects", {}) == "No Vercel projects are being tracked in the Analytics panel yet."


def test_untrack_unknown_vercel_project(registry):
    result = registry.dispatch("untrack_vercel_project", {"project_id": "prj_never"})
    assert "wasn't being tracked" in result
