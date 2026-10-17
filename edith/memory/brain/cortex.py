"""The brain's LLM steps (A-MEM, arXiv:2502.12110): perceive a new memory into a
structured note, then decide its links and how its neighbors should evolve.
Pure functions over an LLM client — no storage here."""

import json
from typing import Any, Optional

from edith.config import MAX_RESPONSE_TOKENS

PERCEIVE_PROMPT = """You are the memory of a personal AI assistant named Eddy. Decide whether this \
should become a long-term memory about the user, and if so, file it.

Regions that already exist in memory (name: note count):
{regions}

Content ({timestamp}):
{content}
{region_hint}
Return JSON:
- worth_remembering: false if this is small talk, an acknowledgement, a one-off lookup with nothing \
learned about the user, or otherwise useless in a future conversation. true otherwise.
- region: the area of the user's life this is about, by topic — e.g. "career", "business", "health", \
"family", "finances", "learning", "hobbies", or "preferences" (how they like things done). Reuse an \
existing region only when the topic really matches; otherwise name a new one (short, lowercase). \
Choose by topic, not by phrasing: "I run 5k three times a week" is health even if a "preferences" \
region exists.
- core: true only for lasting facts about who the user is (identity, role, relationships), stable \
preferences, or instructions on how Eddy should behave — things worth having in mind in every \
conversation. Plans, events, projects, and one-off details are not core.
- context: ONE sentence stating what this memory says about the user, written as a standalone fact \
("Prefers short, direct answers without bullet points.").
- keywords: at least 3 salient keywords, most important first, no names of speakers or timestamps.
- tags: at least 3 broad categories.

{{"worth_remembering": true, "region": "...", "core": false, "context": "...", "keywords": [...], "tags": [...]}}"""

EVOLVE_PROMPT = """You maintain the memory network of a personal AI assistant. A new memory was just \
stored. Decide how it relates to its nearest existing memories.

New memory:
{new_note}

Nearest existing memories:
{neighbors}

Return JSON:
- links: neighbors meaningfully related to the new memory (same project, person, theme, cause and \
effect, an update or contradiction) — each with a short relation like "updates", "contradicts", \
"part of", "same project", "caused by". Skip superficial word overlap.
- tags: the new memory's final tags, refined given its neighbors.
- neighbor_updates: neighbors whose understanding should change because of the new memory — give a \
rewritten context and/or tags/keywords. Add "superseded": true ONLY when the new memory makes that \
neighbor no longer true (e.g. "left Acme" vs "works at Acme"), and say in its context that it is past. \
Never invent facts; only reframe what the memories say. Omit neighbors that should not change.

{{"links": [{{"id": 0, "relation": "..."}}], "tags": [...], "neighbor_updates": [{{"id": 0, "context": "...", "tags": [...], "keywords": [...]}}]}}"""


def _json(client: Any, model: str, prompt: str, attempts: int = 2) -> dict[str, Any]:
    """One retry on malformed JSON — small models occasionally emit a broken object."""
    for attempt in range(attempts):
        try:
            return _json_once(client, model, prompt)
        except json.JSONDecodeError:
            if attempt == attempts - 1:
                raise
    return {}


def _json_once(client: Any, model: str, prompt: str) -> dict[str, Any]:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=MAX_RESPONSE_TOKENS,
        temperature=0,
        extra_body={"reasoning": {"enabled": False}},
    )
    text = (resp.choices[0].message.content or "").strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


def _strings(value: Any) -> list[str]:
    return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []


def describe(note: dict[str, Any]) -> str:
    core = ", core" if note.get("core") else ""
    return (
        f"[id {note['id']}] ({note['created_at'][:10]}, region: {note['region']}{core}) {note['context']}\n"
        f"  keywords: {', '.join(note['keywords'])} | tags: {', '.join(note['tags'])}\n"
        f"  original: {note['content'][:600]}"
    )


def embedding_text(note: dict[str, Any]) -> str:
    return "\n".join(
        [note["content"], note["context"], "keywords: " + ", ".join(note["keywords"]), "tags: " + ", ".join(note["tags"])]
    )


def perceive(
    client: Any,
    model: str,
    content: str,
    timestamp: str,
    regions: list[tuple[str, int]],
    region_hint: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Note attributes for content, or None if it isn't worth remembering."""
    parsed = _json(
        client,
        model,
        PERCEIVE_PROMPT.format(
            regions="\n".join(f"- {name}: {n}" for name, n in regions) or "(none yet — this is a brand-new memory)",
            timestamp=timestamp,
            content=content,
            region_hint=f"\nThe caller asked for this to go in region: {region_hint}\n" if region_hint else "",
        ),
    )
    if parsed.get("worth_remembering") is False:
        return None
    region = (region_hint or str(parsed.get("region") or "")).strip().lower() or "general"
    return {
        "region": region,
        "core": parsed.get("core") is True,
        "context": str(parsed.get("context") or "").strip() or content[:200],
        "keywords": _strings(parsed.get("keywords")),
        "tags": _strings(parsed.get("tags")),
    }


def evolve(client: Any, model: str, note: dict[str, Any], neighbors: list[dict[str, Any]]) -> dict[str, Any]:
    """{"links": [(id, relation)], "tags": [...], "updates": [{id, context?, tags?, keywords?, core?}]},
    where core=False appears only for a neighbor the new memory superseded;
    restricted to ids that are actually among the neighbors."""
    parsed = _json(
        client,
        model,
        EVOLVE_PROMPT.format(new_note=describe(note), neighbors="\n\n".join(describe(n) for n in neighbors)),
    )
    known = {n["id"] for n in neighbors}

    links = []
    for item in parsed.get("links") or []:
        if isinstance(item, dict) and item.get("id") in known:
            links.append((item["id"], str(item.get("relation") or "related").strip()))
        elif isinstance(item, int) and item in known:
            links.append((item, "related"))

    updates = []
    for item in parsed.get("neighbor_updates") or []:
        if not isinstance(item, dict) or item.get("id") not in known:
            continue
        update: dict[str, Any] = {"id": item["id"]}
        if str(item.get("context") or "").strip():
            update["context"] = str(item["context"]).strip()
        for field in ("tags", "keywords"):
            if _strings(item.get(field)):
                update[field] = _strings(item[field])
        if item.get("superseded") is True:
            update["core"] = False
        if len(update) > 1:
            updates.append(update)

    return {"links": links, "tags": _strings(parsed.get("tags")), "updates": updates}
