"""Tests for edith/tools/productivity/notes.py's save_fact duplicate-surfacing hint.

Live use surfaced a real memory bug: the model would save a new fact under a
slightly different key than one already covering the same thing (e.g. 'job'
vs 'current_role'), leaving stale/conflicting duplicates in the profile with
no way for the model to notice. save_fact now returns any other facts
already stored in the same category so the model can catch and clean up
overlap right when it happens.
"""

import pytest

from edith.memory import db, store
from edith.tools.productivity import notes
from edith.tools.registry import ToolRegistry


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def _registry(conn):
    registry = ToolRegistry()
    notes.register(registry, conn, qdrant_client=None, genai_client=None)
    return registry


def test_save_fact_flags_other_facts_in_same_category(conn):
    registry = _registry(conn)
    registry.dispatch("save_fact", {"key": "current_role", "value": "PM at Allore", "category": "identity"})

    result = registry.dispatch("save_fact", {"key": "job", "value": "Product Manager", "category": "identity"})

    assert "current_role=PM at Allore" in result
    assert "Saved: job = Product Manager" in result


def test_save_fact_does_not_flag_itself_on_update(conn):
    registry = _registry(conn)
    registry.dispatch("save_fact", {"key": "current_role", "value": "PM at Allore", "category": "identity"})

    result = registry.dispatch(
        "save_fact", {"key": "current_role", "value": "Senior PM at Allore", "category": "identity"}
    )

    assert "check for overlap" not in result
    assert store.get_fact(conn, "current_role") == "Senior PM at Allore"


def test_save_fact_no_hint_without_category(conn):
    registry = _registry(conn)
    registry.dispatch("save_fact", {"key": "favorite_color", "value": "blue", "category": ""})

    result = registry.dispatch("save_fact", {"key": "favorite_food", "value": "pizza", "category": ""})

    assert "check for overlap" not in result
