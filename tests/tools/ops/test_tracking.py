import pytest

from edith.memory.storage import sqlite
from edith.tools.ops import tracking
from edith.tools.base import ToolContext
from edith.tools.registry import ToolRegistry


@pytest.fixture
def conn(tmp_path):
    c = sqlite.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def registry(conn):
    r = ToolRegistry(ToolContext(conn=conn))
    r.register_module(tracking)
    return r


def test_track_list_untrack_url(registry):
    result = registry.dispatch("track_url", {"url": "https://example.com/news", "note": "daily tech news"})
    assert "example.com/news" in result

    listed = registry.dispatch("list_tracked_urls", {})
    assert "https://example.com/news" in listed
    assert "daily tech news" in listed

    untracked = registry.dispatch("untrack_url", {"url": "https://example.com/news"})
    assert "Stopped tracking" in untracked
    assert registry.dispatch("list_tracked_urls", {}) == "No URLs are being tracked yet."


def test_untrack_unknown_url(registry):
    result = registry.dispatch("untrack_url", {"url": "https://never-tracked.example"})
    assert "wasn't being tracked" in result


def test_track_url_upserts_on_repeat(registry):
    registry.dispatch("track_url", {"url": "https://example.com", "note": "first note"})
    registry.dispatch("track_url", {"url": "https://example.com", "note": "updated note"})

    listed = registry.dispatch("list_tracked_urls", {})
    assert listed.count("https://example.com") == 1
    assert "updated note" in listed
    assert "first note" not in listed
