from types import SimpleNamespace

import openai

from edith.startup_finder import llm


class _Completions:
    def __init__(self, fail):
        self.fail, self.calls = set(fail), []

    def create(self, model, messages, temperature, timeout):
        self.calls.append(model)
        if model in self.fail:
            raise openai.APIConnectionError(request=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=f'{{"from": "{model}"}}'))])


def _llm(fail=()):
    c = llm.OpenRouterLLM("k", ["qwen/qwen3.8-flash"])
    comp = _Completions(fail)
    c.models._client = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    return c, comp


def test_primary_model_used():
    c, comp = _llm()
    assert "muse" in c.models.generate_content("meta/muse-spark-1.3", "hi").text
    assert comp.calls == ["meta/muse-spark-1.3"]


def test_falls_back_to_qwen():
    c, comp = _llm(fail={"meta/muse-spark-1.3"})
    assert "qwen" in c.models.generate_content("meta/muse-spark-1.3", "hi").text
    assert comp.calls == ["meta/muse-spark-1.3", "qwen/qwen3.8-flash"]


def test_from_settings_needs_key():
    assert llm.from_settings(SimpleNamespace()) is None
    assert llm.from_settings(SimpleNamespace(api_key="k", startup_finder_fallback_model="q")) is not None
