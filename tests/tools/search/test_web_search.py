from types import SimpleNamespace

from edith.tools.base import ToolContext
from edith.tools.registry import ToolRegistry
from edith.tools.search import web_search


class _FakeOpenRouter:
    def __init__(self, reply):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.reply = reply

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))])


def test_web_search_without_gemini_uses_openrouter_web_plugin():
    llm = _FakeOpenRouter("Paris (source: wikipedia.org)")
    registry = ToolRegistry(ToolContext(llm_client=llm, settings=SimpleNamespace(model="qwen/test")))
    registry.register_module(web_search)

    assert registry.dispatch("web_search", {"query": "capital of France"}) == "Paris (source: wikipedia.org)"
    assert llm.calls[0]["model"] == "qwen/test"
    assert llm.calls[0]["extra_body"] == {"plugins": [{"id": "web"}]}


def test_grounded_search_prefers_gemini_when_configured():
    gemini = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(text="from google")))
    llm = _FakeOpenRouter("from openrouter")
    assert web_search.grounded_search(gemini, "g", llm, "q", "x") == "from google"
    assert llm.calls == []
