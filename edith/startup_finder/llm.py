import logging
from types import SimpleNamespace
from typing import Any, Optional

import openai

from edith.config import OPENROUTER_BASE_URL

logger = logging.getLogger("edith.startup_finder.llm")

TIMEOUT = 120


class _Models:
    def __init__(self, client: openai.OpenAI, fallbacks: list[str]):
        self._client = client
        self._fallbacks = fallbacks

    def generate_content(self, model: str, contents: str) -> SimpleNamespace:
        last: Optional[Exception] = None
        for name in dict.fromkeys([model, *self._fallbacks]):
            try:
                resp = self._client.chat.completions.create(
                    model=name,
                    messages=[{"role": "user", "content": contents}],
                    temperature=0.3,
                    timeout=TIMEOUT,
                )
                text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
                if text:
                    return SimpleNamespace(text=text)
                last = RuntimeError(f"{name} returned an empty response")
            except openai.OpenAIError as e:
                last = e
            logger.warning("startup finder model %s failed: %s", name, last)
        raise RuntimeError(f"all startup finder models failed: {last}")


class OpenRouterLLM:
    def __init__(self, api_key: str, fallbacks: list[str]):
        self.models = _Models(openai.OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key), fallbacks)


def from_settings(settings: Any) -> Optional[OpenRouterLLM]:
    key = getattr(settings, "api_key", "")
    if not key:
        return None
    return OpenRouterLLM(key, [m for m in [getattr(settings, "startup_finder_fallback_model", "")] if m])
