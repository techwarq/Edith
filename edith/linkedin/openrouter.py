"""OpenRouter clients for LinkedIn Growth Engine.

Text: qwen/qwen3.7-flash ($0.03/$0.13 per 1M) — cheapest Qwen, verified via /api/v1/models
Image: meta/muse-image ($0.01/image flat) — cheapest image, fallback google/gemini-2.5-flash-image
"""
import base64
import json
import logging
import os
from typing import Any

import requests

from edith.config import OPENROUTER_BASE_URL

logger = logging.getLogger("edith.linkedin.openrouter")

DEFAULT_TEXT_MODEL = os.environ.get("LINKEDIN_TEXT_MODEL", "qwen/qwen3.7-flash")
FALLBACK_TEXT_MODEL = os.environ.get("LINKEDIN_FALLBACK_TEXT_MODEL", "qwen/qwen3-30b-a3b-instruct-2507")
DEFAULT_IMAGE_MODEL = os.environ.get("LINKEDIN_IMAGE_MODEL", "meta/muse-image")
FALLBACK_IMAGE_MODEL = os.environ.get("LINKEDIN_FALLBACK_IMAGE_MODEL", "google/gemini-2.5-flash-image")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

def _openai_client():
    import openai
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return openai.OpenAI(base_url=OPENROUTER_BASE_URL, api_key=key)

def generate_linkedin_post(
    messages: list[dict],
    model: str | None = None,
) -> dict[str, Any]:
    """Call Qwen via OpenRouter chat completions, expect JSON. Returns dict with usage."""
    model = model or DEFAULT_TEXT_MODEL
    client = _openai_client()
    # qwen3.7-flash uses reasoning_tokens that eat max_tokens budget (2153 reasoning + 300 output seen).
    # Must give large budget or we get empty content (finish truncated).
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=8192,
        temperature=0.85,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    usage = getattr(resp, "usage", None)
    # Try parse JSON; if model wrapped in markdown, strip
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # try extract JSON block
        import re
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
        else:
            raise
    # Normalize expected fields
    commentary = data.get("commentary") or data.get("post") or data.get("text") or ""
    # LinkedIn limit 3000 chars, we target 900-1300 but enforce cap
    if len(commentary) > 3000:
        commentary = commentary[:2997] + "..."
    data["commentary"] = commentary
    # ensure hashtags list
    if isinstance(data.get("hashtags"), str):
        data["hashtags"] = [h.strip() for h in data["hashtags"].split() if h.startswith("#")]
    data.setdefault("hashtags", [])
    data.setdefault("pillar", "")
    data.setdefault("hook", commentary.split("\n")[0][:120] if commentary else "")
    data.setdefault("cta", "")
    data.setdefault("image_prompt", "")
    data.setdefault("why_this_will_work", "")
    # usage meta
    data["_model"] = model
    if usage:
        data["_usage"] = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
        prompt_cost = getattr(usage, "cost", None)  # OpenRouter sometimes returns cost in usage
        data["_cost"] = prompt_cost
    else:
        data["_usage"] = {}
    return data

def generate_image(prompt: str, model: str | None = None, aspect_ratio: str = "1:1") -> dict[str, Any]:
    """Call OpenRouter Images API. Returns {b64_json, media_type, cost}. Uses cheapest Muse Image."""
    model = model or DEFAULT_IMAGE_MODEL
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    url = "https://openrouter.ai/api/v1/images"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_REFERRER", "https://edith.local"),
        "X-Title": os.environ.get("OPENROUTER_TITLE", "Edith LinkedIn Growth Engine"),
    }
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
    }
    # aspect_ratio supported by most models
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio

    resp = requests.post(url, headers=headers, json=payload, timeout=90)
    if resp.status_code != 200:
        # fallback attempt
        logger.warning("image gen failed %s %s, trying fallback %s", resp.status_code, resp.text[:500], FALLBACK_IMAGE_MODEL)
        if model != FALLBACK_IMAGE_MODEL:
            payload["model"] = FALLBACK_IMAGE_MODEL
            resp = requests.post(url, headers=headers, json=payload, timeout=90)
    resp.raise_for_status()
    j = resp.json()
    # OpenRouter Images API returns {data:[{b64_json, media_type}], usage:{cost}}
    data0 = (j.get("data") or [{}])[0]
    b64 = data0.get("b64_json") or data0.get("b64") or ""
    media_type = data0.get("media_type") or "image/png"
    usage = j.get("usage") or {}
    cost = usage.get("cost") or usage.get("total_cost") or 0.01
    # If no b64 but url returned, fetch it
    if not b64 and data0.get("url"):
        try:
            img_resp = requests.get(data0["url"], timeout=30)
            img_resp.raise_for_status()
            b64 = base64.b64encode(img_resp.content).decode("ascii")
            media_type = img_resp.headers.get("content-type", "image/png")
        except Exception as e:
            logger.warning("fetch image url failed: %s", e)
    return {"b64_json": b64, "media_type": media_type, "model": payload["model"], "cost": cost, "raw": j}

def generate_text_fallback(messages: list[dict]) -> dict[str, Any]:
    """Try primary then fallback model."""
    try:
        return generate_linkedin_post(messages, model=DEFAULT_TEXT_MODEL)
    except Exception as e:
        logger.warning("primary text model failed (%s), fallback to %s: %s", DEFAULT_TEXT_MODEL, FALLBACK_TEXT_MODEL, e)
        return generate_linkedin_post(messages, model=FALLBACK_TEXT_MODEL)

def plan_calendar(messages: list[dict]) -> list[dict]:
    """Generate 7-day plan via Qwen."""
    client = _openai_client()
    resp = client.chat.completions.create(
        model=DEFAULT_TEXT_MODEL,
        messages=messages,
        max_tokens=8192,
        temperature=0.8,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "plan" in data:
            data = data["plan"]
        if isinstance(data, dict) and "days" in data:
            data = data["days"]
        if isinstance(data, list):
            return data
        # sometimes returns {"0": {...}, "1": {...}}
        if isinstance(data, dict):
            return list(data.values())
        return []
    except Exception:
        logger.exception("plan_calendar parse failed")
        return []
