import pytest

from edith.memory.brain import Brain
from edith.memory.storage import sqlite
from edith.tools.base import ToolContext
from edith.tools.productivity import notes
from edith.tools.registry import ToolRegistry
from tests.memory.test_brain import FakeLLM, FakeQdrant


@pytest.fixture
def conn(tmp_path):
    c = sqlite.connect(tmp_path / "test.db")
    yield c
    c.close()


def _registry(conn, brain):
    registry = ToolRegistry(ToolContext(conn=conn, brain=brain))
    registry.register_module(notes)
    return registry


def test_remember_reports_where_it_was_filed(conn):
    llm = FakeLLM()
    llm.perceive = lambda p: {
        "worth_remembering": True, "region": "preferences", "core": True,
        "context": "Prefers calls after 4pm.", "keywords": [], "tags": [],
    }
    registry = _registry(conn, Brain(conn, llm, "m", FakeQdrant()))

    result = registry.dispatch("remember", {"content": "Alex prefers calls after 4pm"})

    assert result == "Remembered as #1 in 'preferences', core: Prefers calls after 4pm."


def test_remember_passes_region_hint(conn):
    registry = _registry(conn, Brain(conn, FakeLLM(), "m", FakeQdrant()))
    result = registry.dispatch("remember", {"content": "Posts on X daily", "region": "content strategy"})
    assert "'content strategy'" in result


def test_remember_without_llm_says_so(conn):
    registry = _registry(conn, Brain(conn))
    assert "isn't configured" in registry.dispatch("remember", {"content": "x"})


def test_recall_and_forget_round_trip(conn):
    brain = Brain(conn, FakeLLM(), "m", FakeQdrant())
    registry = _registry(conn, brain)
    note = brain.remember("training for a half marathon in march")

    assert f"#{note['id']}" in registry.dispatch("recall", {"query": "half marathon"})
    assert registry.dispatch("forget_memory", {"note_id": note["id"]}) == f"Forgot memory #{note['id']}."
    assert registry.dispatch("recall", {"query": "half marathon"}) == "No related memories found."
    assert registry.dispatch("forget_memory", {"note_id": note["id"]}) == f"No memory #{note['id']} exists."
