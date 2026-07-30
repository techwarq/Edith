"""Cost estimation for LLM/STT/TTS calls.

These are USD list-price estimates, not real invoiced numbers pulled from any
provider billing API — Gemini/OpenRouter don't return per-call cost in the
response, only token counts, so cost has to be computed client-side from a
rate table. Update TEXT_MODEL_PRICING/whisper/TTS rates here if a provider
changes pricing; nothing else needs to change since every call site goes
through estimate_llm_cost()/estimate_stt_cost()/estimate_tts_cost() below.
"""

# USD per 1M tokens, (input_rate, output_rate). qwen3-coder-next's rate is the
# real one Sonali quoted when picking it (see edith-project-overview memory);
# gemini-3.5-flash is an estimate in the same ballpark as other Gemini Flash
# tiers — verify against https://ai.google.dev/pricing before trusting exact
# dollar figures, but it's fine for relative/trend tracking either way.
TEXT_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-3.5-flash": (0.075, 0.30),
    "qwen/qwen3-coder-next": (0.11, 0.80),
}
DEFAULT_TEXT_PRICING = (0.20, 0.80)  # fallback for an unrecognized model, so cost tracking degrades gracefully instead of silently reporting $0

# Whisper STT: OpenRouter-quoted rate (see edith/voice.py / project memory).
STT_PRICE_PER_MINUTE: dict[str, float] = {
    "openai/whisper-large-v3": 0.0015,
}
DEFAULT_STT_PRICE_PER_MINUTE = 0.0015

# Gemini native TTS: no confirmed rate card seen yet — placeholder in the
# ballpark of other neural TTS pricing (~$15/1M chars). Flagged here, not
# guessed silently, so spending totals don't look more precise than they are.
TTS_PRICE_PER_1K_CHARS: dict[str, float] = {
    "gemini-3.1-flash-tts-preview": 0.015,
}
DEFAULT_TTS_PRICE_PER_1K_CHARS = 0.015


def estimate_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_rate, out_rate = TEXT_MODEL_PRICING.get(model, DEFAULT_TEXT_PRICING)
    return (prompt_tokens / 1_000_000) * in_rate + (completion_tokens / 1_000_000) * out_rate


def estimate_stt_cost(model: str, audio_seconds: float) -> float:
    rate = STT_PRICE_PER_MINUTE.get(model, DEFAULT_STT_PRICE_PER_MINUTE)
    return (audio_seconds / 60.0) * rate


def estimate_tts_cost(model: str, char_count: int) -> float:
    rate = TTS_PRICE_PER_1K_CHARS.get(model, DEFAULT_TTS_PRICE_PER_1K_CHARS)
    return (char_count / 1000.0) * rate
