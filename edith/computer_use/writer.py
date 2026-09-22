"""Free-text generation for fill/press actions. Jev (decide.py) never
generates text itself — it only picks a job (click/fill/press/...); the
literal text or key combo comes from the goal verbatim when it's quoted
there, and only goes through a real LLM (OpenRouter, qwen/qwen3.7-flash by
default) when the goal doesn't already spell it out. Matches the same
separation computer-use-jev's own DESIGN.md uses: the classifier decides
what to do, never what to type.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import openai

from edith.config import OPENROUTER_BASE_URL
from edith.llm.client import make_client

_QUOTED_RE = re.compile(r'"([^"]*)"')
_KEY_COMBO_RE = re.compile(r"(?i)\b(?:cmd|command|ctrl|control|opt|option|alt|shift)\+[a-z0-9]+(?:\+[a-z0-9]+)*\b")


def quoted_segment(goal: str) -> Optional[str]:
    """The exact text to enter, taken verbatim from the goal — never generated."""
    m = _QUOTED_RE.search(goal)
    return m.group(1) if m else None


def key_combo(goal: str) -> Optional[str]:
    """A keyboard shortcut named in the goal, e.g. 'cmd+l', lowercased."""
    m = _KEY_COMBO_RE.search(goal)
    return m.group(0).lower() if m else None


def make_writer_client(api_key: str) -> openai.OpenAI:
    return make_client(api_key, base_url=OPENROUTER_BASE_URL)


def app_to_launch(client: openai.OpenAI, model: str, goal: str, running_apps: list[str]) -> Optional[str]:
    """If `goal` names or clearly implies one specific application that
    isn't already in `running_apps`, returns its macOS application name to
    launch via `open -a` — e.g. "open Slack and check messages" when Slack
    isn't running. Returns None when the goal's target is already running,
    or the goal names no specific application at all — this only ever
    extracts a name the goal itself supplies, the same separation as
    quoted_segment/compose_fill_text; it never invents an app to open."""
    packet = {"goal": goal, "running_applications": running_apps}
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "A macOS automation agent needs to know whether `goal` requires an application "
                    "that is not already in running_applications. If the goal names or clearly implies "
                    "one specific application (e.g. 'Slack', 'Spotify', 'Mail') and it is NOT already in "
                    "running_applications, return its exact macOS application name to launch. If the "
                    "goal's target application is already running, or the goal names no specific "
                    "application, set launch to false. Never invent an application the goal doesn't "
                    'itself name or clearly imply. Respond with strict JSON only: {"launch": bool, '
                    '"app_name": string, "reason": string}'
                ),
            },
            {"role": "user", "content": json.dumps(packet)},
        ],
        response_format={"type": "json_object"},
        # Generous relative to the tiny JSON output: the default writer model
        # (qwen3.7-flash) spends a chunk of its budget on internal reasoning
        # tokens before ever emitting content — too tight a cap here means it
        # burns the whole budget thinking and returns None content, the same
        # failure mode llm/client.py's run_completion_with_tools guards against.
        max_tokens=400,
    )
    try:
        data = json.loads(resp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return None
    if not data.get("launch"):
        return None
    name = (data.get("app_name") or "").strip()
    return name or None


def compose_fill_text(client: openai.OpenAI, model: str, goal: str, field_label: str, history: list[str]) -> str:
    """Composes text for a field the goal doesn't already quote — e.g. "search
    for the Elliot Choy video" naming a search box by role/label, not by
    exact query text. Returns "" if the model declines (e.g. it looks like a
    credential field)."""
    packet = {"goal": goal, "field_label": field_label, "recent_actions": history[-6:]}
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You fill in one text field on a user's screen. You get the user's goal, the "
                    "field's label, and recent actions. Decide the exact string to type. Never "
                    "invent credentials, passwords, or personal data — for those, or when the field "
                    "shouldn't be filled, set fill to false. Respond with strict JSON only: "
                    '{"fill": bool, "text": string, "reason": string}'
                ),
            },
            {"role": "user", "content": json.dumps(packet)},
        ],
        response_format={"type": "json_object"},
        # See app_to_launch's comment: the writer model spends part of its
        # budget on internal reasoning tokens before emitting content, so a
        # cap this close to the JSON's own size truncates mid-string instead
        # of returning something json.loads can parse — confirmed live: 200
        # cut a real completion off after '{"fill": true, "text": "...", "reason": "The'.
        max_tokens=400,
    )
    try:
        data = json.loads(resp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return ""
    return data.get("text", "").strip() if data.get("fill") else ""
