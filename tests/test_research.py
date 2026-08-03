"""Tests for edith/tools/research.py's deep_research tool — the previously-
deferred multi-step research mode: decompose into sub-questions, grounded
search per sub-question, synthesize one sourced answer."""

from types import SimpleNamespace

from edith.tools import research
from edith.tools.registry import ToolRegistry


class _FakeClient:
    """Fakes genai.Client.models.generate_content with scripted responses,
    consumed in call order: decompose, then one grounded search per
    sub-question, then synthesize."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

        class _Models:
            def generate_content(inner_self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(text=self._responses.pop(0))

        self.models = _Models()


def test_deep_research_decomposes_searches_and_synthesizes():
    client = _FakeClient(
        [
            '["What is X?", "What is Y?"]',  # decompose
            "X is a thing (source: a.com)",  # sub-question 1
            "Y is another thing (source: b.com)",  # sub-question 2
            "X and Y together: a synthesized answer.\nSources: a.com, b.com",  # synthesize
        ]
    )
    registry = ToolRegistry()
    research.register(registry, client, "fake-model", qdrant_client=None)

    result = registry.dispatch("deep_research", {"query": "Compare X and Y"})

    assert result == "X and Y together: a synthesized answer.\nSources: a.com, b.com"
    assert len(client.calls) == 4


def test_deep_research_falls_back_to_original_query_on_bad_decompose_json():
    client = _FakeClient(
        [
            "not json at all",  # decompose fails to parse
            "Answer to the original query (source: a.com)",  # single sub-question = original query
            "Final synthesized answer.",  # synthesize
        ]
    )
    registry = ToolRegistry()
    research.register(registry, client, "fake-model", qdrant_client=None)

    result = registry.dispatch("deep_research", {"query": "What's happening with widgets?"})

    assert result == "Final synthesized answer."
    assert len(client.calls) == 3


def test_deep_research_reports_failed_subquestion_without_crashing():
    class _RaisingModels:
        def __init__(self):
            self.n = 0

        def generate_content(self, **kwargs):
            self.n += 1
            if self.n == 1:
                return SimpleNamespace(text='["only question"]')
            if self.n == 2:
                raise RuntimeError("network blip")
            return SimpleNamespace(text="Synthesized despite one failed search.")

    client = SimpleNamespace(models=_RaisingModels())
    registry = ToolRegistry()
    research.register(registry, client, "fake-model", qdrant_client=None)

    result = registry.dispatch("deep_research", {"query": "anything"})

    assert result == "Synthesized despite one failed search."
