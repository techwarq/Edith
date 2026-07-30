from edith.observability import pricing


def test_estimate_llm_cost_known_model():
    cost = pricing.estimate_llm_cost("qwen/qwen3-coder-next", 1_000_000, 1_000_000)
    assert cost == 0.11 + 0.80


def test_estimate_llm_cost_unknown_model_falls_back_to_default_rate():
    cost = pricing.estimate_llm_cost("some/unseen-model", 1_000_000, 0)
    in_rate, _ = pricing.DEFAULT_TEXT_PRICING
    assert cost == in_rate


def test_estimate_llm_cost_zero_tokens_is_free():
    assert pricing.estimate_llm_cost("gemini-3.5-flash", 0, 0) == 0.0


def test_estimate_stt_cost():
    cost = pricing.estimate_stt_cost("openai/whisper-large-v3", 60)
    assert cost == 0.0015


def test_estimate_tts_cost():
    cost = pricing.estimate_tts_cost("gemini-3.1-flash-tts-preview", 1000)
    assert cost == 0.015
