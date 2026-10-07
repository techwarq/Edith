from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger("edith.computer_use.typesafe_client")

GATEWAY_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "~typesafe/jev-latest"
FALLBACK_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
FALLBACK_MODEL = "qwen/qwen3.7-flash"
_TIMEOUT_SECONDS = 30


class TypeSafeError(Exception):
    pass


@dataclass(frozen=True)
class Question:
    type: str
    instructions: str
    criteria: Any


def choice(instructions: str, criteria: dict[str, str]) -> Question:
    return Question("choice", instructions, criteria)


def noul(instructions: str, criteria: dict[str, str] | None = None) -> Question:
    return Question("noul", instructions, criteria or {"true": "yes", "false": "no"})


def score(instructions: str, levels: list[str]) -> Question:
    return Question("score", instructions, levels)


@dataclass(frozen=True)
class Answer:
    type: str
    choice: str = ""
    noul: float = 0.0
    score: float = 0.0
    probabilities: dict[str, float] | None = None
    confidence: float = 0.0


def _questions_body(questions: dict[str, Question]) -> dict:
    return {qid: {"type": q.type, "instructions": q.instructions, "criteria": q.criteria} for qid, q in questions.items()}


def _describe_questions(questions: dict[str, Question]) -> str:
    lines = []
    for qid, q in questions.items():
        if q.type == "noul":
            c = q.criteria or {}
            lines.append(
                f'- {qid} (noul): {q.instructions} Criteria: true="{c.get("true", "")}" false="{c.get("false", "")}" '
                '-> return {"type":"noul","noul":0.0-1.0}'
            )
        elif q.type == "choice":
            opts = " | ".join(f"{k}: {v}" for k, v in q.criteria.items())
            lines.append(
                f"- {qid} (choice): {q.instructions} Options: {{ {opts} }} "
                '-> return {"type":"choice","choice":"<one option>","probabilities":{...},"confidence":0-1}'
            )
        elif q.type == "score":
            levels = " | ".join(f'{i}="{c}"' for i, c in enumerate(q.criteria))
            lines.append(
                f"- {qid} (score): {q.instructions} Levels: [ {levels} ] "
                '-> return {"type":"score","score":0-N,"legend":{...},"probabilities":{...},"confidence":0-1}'
            )
    return "\n".join(lines)


def _build_fallback_prompt(state: Any, questions: dict[str, Question]) -> str:
    state_str = json.dumps(state, indent=2, sort_keys=True, default=str)
    return (
        "You are Jev, a structured decision model from TypeSafe. You make fast, calibrated decisions. "
        "You do NOT generate prose.\n\n"
        f"STATE (what to judge):\n{state_str}\n\n"
        f"QUESTIONS (answer ALL in parallel, independently):\n{_describe_questions(questions)}\n\n"
        "RULES:\n"
        '- Return ONLY valid JSON: {"answers": {"<id>": {...}, ...}}\n'
        '- For noul: {"type":"noul","noul": 0.0-1.0} where noul is probability true (1=yes, 0=no)\n'
        '- For choice: {"type":"choice","choice":"<exact option key>","probabilities":{"opt":0-1,...},"confidence":0-1} '
        "probabilities sum to 1, choice is highest prob, confidence high when one option dominates\n"
        '- For score: {"type":"score","score": weighted mean 0-(n-1),"legend":{"0":"...","1":"..."},'
        '"probabilities":{"0":0-1,...},"confidence":0-1} score may be fractional (e.g. 1.3)\n'
        "- Be calibrated: probabilities must match your actual uncertainty"
    )


def _normalize_fallback_answers(raw: dict, questions: dict[str, Question]) -> dict[str, Answer]:
    answers: dict[str, Answer] = {}
    for qid, q in questions.items():
        r = raw.get(qid) or {}
        if q.type == "noul":
            v = r.get("noul")
            v = float(v) if isinstance(v, (int, float)) else 0.5
            answers[qid] = Answer(type="noul", noul=max(0.0, min(1.0, v)))
        elif q.type == "choice":
            opts = list(q.criteria.keys())
            ch = r.get("choice")
            if ch not in opts:
                ch = opts[0] if opts else ""
            probs = dict(r.get("probabilities") or {})
            if sum(probs.values()) == 0 and opts:
                for o in opts:
                    probs[o] = 0.9 if o == ch else 0.1 / max(len(opts) - 1, 1)
            confidence = r.get("confidence")
            confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.7
            answers[qid] = Answer(type="choice", choice=ch, probabilities=probs, confidence=confidence)
        elif q.type == "score":
            n = len(q.criteria)
            sc = r.get("score")
            sc = float(sc) if isinstance(sc, (int, float)) else 1.0
            confidence = r.get("confidence")
            confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.7
            answers[qid] = Answer(type="score", score=max(0.0, min(float(max(n - 1, 0)), sc)), confidence=confidence)
    return answers


class TypeSafeClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise TypeSafeError("OPENROUTER_API_KEY isn't set — Jev is called through OpenRouter, same key as everything else.")
        self._api_key = api_key
        self.last_source = ""

    def ask(self, state: Any, questions: dict[str, Question]) -> dict[str, Answer]:
        try:
            answers = self._ask_real_jev(state, questions)
            self.last_source = "jev"
            print(f"  [Jev] openrouter-decisions -> {JEV_MODEL}")
        except TypeSafeError as e:
            print(f"  [Jev] fallback to {FALLBACK_MODEL} simulation ({e})")
            answers = self._ask_fallback(state, questions)
            self.last_source = "fallback"

        missing = set(questions) - set(answers)
        if missing:
            raise TypeSafeError(f"Jev's response is missing answers for: {sorted(missing)}")
        return answers

    def _ask_real_jev(self, state: Any, questions: dict[str, Question]) -> dict[str, Answer]:
        body = {"model": JEV_MODEL, "state": state, "questions": _questions_body(questions)}
        try:
            resp = requests.post(
                GATEWAY_ENDPOINT,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as e:
            raise TypeSafeError(f"network error calling Jev: {e}") from e

        try:
            payload = resp.json()
        except ValueError as e:
            raise TypeSafeError(f"Jev returned a non-JSON response (status {resp.status_code})") from e

        if resp.status_code >= 400:
            message = payload.get("message") or payload.get("error") or resp.text
            raise TypeSafeError(f"Jev returned {resp.status_code}: {message}")

        raw_answers = payload.get("answers") or {}
        answers: dict[str, Answer] = {}
        for qid, raw in raw_answers.items():
            answers[qid] = Answer(
                type=raw.get("type", ""),
                choice=raw.get("choice", ""),
                noul=float(raw.get("noul", 0.0) or 0.0),
                score=float(raw.get("score", 0.0) or 0.0),
                probabilities=raw.get("probabilities"),
                confidence=float(raw.get("confidence", 0.0) or 0.0),
            )
        return answers

    def _ask_fallback(self, state: Any, questions: dict[str, Question]) -> dict[str, Answer]:
        import openai

        client = openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=self._api_key)
        prompt = _build_fallback_prompt(state, questions)
        try:
            resp = client.chat.completions.create(
                model=FALLBACK_MODEL,
                messages=[
                    {"role": "system", "content": 'You are Jev. Return ONLY JSON with {"answers": {...}}. No markdown.'},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=4000,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            raise TypeSafeError(f"qwen fallback simulation also failed: {e}") from e

        content = resp.choices[0].message.content or "{}"
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"answers": {}}
        raw = parsed.get("answers", parsed)
        return _normalize_fallback_answers(raw, questions)
