"""Representative test for browse.py's propose-tool queuing logic — pure DB
logic, no browser needed. The browser-automation paths (browse_url,
execute_submit_form) are inherently live-only; see edith/whatsapp.py's tests
for the same reasoning applied to WhatsApp automation.
"""

import pytest

from edith.integrations import browse
from edith.memory import db, store
from edith.tools.registry import ToolRegistry


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_fill_form_queues_pending_action(conn):
    registry = ToolRegistry()
    browse.register(registry, conn)

    result = registry.dispatch(
        "fill_form",
        {"url": "https://example.com/contact", "field_values": {"name": "Sonali", "email": "sonali@example.com"}},
    )

    assert "Queued as action #" in result
    pending = store.get_pending_actions(conn)
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "submit_form"
    assert pending[0]["args"] == {
        "url": "https://example.com/contact",
        "field_values": {"name": "Sonali", "email": "sonali@example.com"},
    }
    assert "name = Sonali" in pending[0]["preview"]


def test_fill_form_does_not_call_a_live_browser(conn, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("fill_form should never open a live browser session — only submit_form (on /approve) does")

    monkeypatch.setattr(browse, "_session", fail_if_called)
    registry = ToolRegistry()
    browse.register(registry, conn)

    registry.dispatch("fill_form", {"url": "https://example.com", "field_values": {"a": "b"}})  # must not raise


def test_execute_submit_form_is_in_executors():
    assert "submit_form" in browse.EXECUTORS
    assert browse.EXECUTORS["submit_form"] is browse.execute_submit_form


def test_browse_url_reports_not_configured_without_credentials(monkeypatch):
    monkeypatch.setattr(browse, "BROWSERBASE_API_KEY", "")
    monkeypatch.setattr(browse, "BROWSERBASE_PROJECT_ID", "")

    result = browse.browse_url("https://example.com")

    assert "ERROR" in result
    assert "not configured" in result.lower() or "isn't configured" in result.lower()
