"""LLM-as-judge eval runner — "how is Edith performing" made concrete.

Each eval case (input, rubric, optional expect_tools) is run through the real
Agent.handle_turn in a dedicated scratch session (never the interactive
session, so evals never pollute real conversation history/facts). Because it
goes through handle_turn, every eval case automatically gets a real trace
with real spans (see edith/observability/tracing.py) — evals aren't a
separate mocked path, they're production tracing pointed at known inputs.

The reply is graded by an LLM judge using a *different* model than the one
being evaluated (reuses the existing OpenRouter client/model that's already
wired up for the voice pipeline's spoken-style rewrite — see
AppContext.client/settings.openrouter_text_model in bootstrap.py) to keep
actor and judge separate rather than having a model grade its own homework.
If expect_tools is set, a passing score can still be downgraded to failed if
a mandated tool wasn't actually called — catches "sounds right but skipped
the real work" replies a judge alone might miss.
"""

import json
import sqlite3
import uuid
from typing import Any, Optional

import openai

from edith.agent import Agent
from edith.memory import store
from edith.observability import queries

JUDGE_SYSTEM_PROMPT = (
    "You are grading an AI assistant's reply for quality. You will be given the "
    "user's input, the assistant's actual reply, and a rubric describing what a "
    "good reply should do. Score strictly against the rubric only — do not reward "
    "unrelated flourishes, and do not penalize style choices the rubric doesn't "
    "mention. "
    'Respond with ONLY a JSON object, no markdown fences: {"score": <float 0.0-1.0>, '
    '"passed": <bool>, "reasoning": "<one or two sentences>"}. passed should be true '
    "only if score >= 0.7."
)


def _judge(client: openai.OpenAI, model: str, user_input: str, reply: str, rubric: str) -> dict[str, Any]:
    prompt = f"User input:\n{user_input}\n\nAssistant reply:\n{reply}\n\nRubric:\n{rubric}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        score = max(0.0, min(1.0, float(parsed.get("score", 0.0))))
        return {
            "score": score,
            "passed": bool(parsed.get("passed", score >= 0.7)),
            "reasoning": str(parsed.get("reasoning", "")),
        }
    except Exception as e:  # noqa: BLE001 — a judge failure shouldn't crash the whole eval run, just fail that one case
        return {"score": 0.0, "passed": False, "reasoning": f"judge error: {e}"}


def _tools_called_for_trace(conn: sqlite3.Connection, trace_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT name FROM spans WHERE trace_id = ? AND kind = 'tool'", (trace_id,)
    ).fetchall()
    return [r["name"] for r in rows]


def _latest_trace_id(conn: sqlite3.Connection, session_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT id FROM traces WHERE session_id = ? AND kind = 'turn' ORDER BY started_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return row["id"] if row else None


def run_eval_case(
    conn: sqlite3.Connection,
    agent: Agent,
    judge_client: openai.OpenAI,
    judge_model: str,
    case: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    scratch_session = store.create_session(conn, agent.model)
    reply = agent.handle_turn(scratch_session, case["input"])
    trace_id = _latest_trace_id(conn, scratch_session)
    tools_called = _tools_called_for_trace(conn, trace_id) if trace_id else []

    judged = _judge(judge_client, judge_model, case["input"], reply, case["rubric"])
    score, passed, reasoning = judged["score"], judged["passed"], judged["reasoning"]

    expect_tools = case.get("expect_tools") or []
    missing = [t for t in expect_tools if t not in tools_called]
    if missing:
        passed = False
        reasoning = f"{reasoning} [missing expected tool call(s): {', '.join(missing)}]".strip()

    conn.execute(
        "INSERT INTO eval_results (run_id, case_id, trace_id, score, passed, judge_reasoning, tools_called) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, case["id"], trace_id, score, int(passed), reasoning, json.dumps(tools_called)),
    )
    store.end_session(conn, scratch_session)
    return {
        "case_id": case["id"],
        "case_name": case["name"],
        "score": score,
        "passed": passed,
        "reasoning": reasoning,
        "tools_called": tools_called,
        "trace_id": trace_id,
    }


def run_eval_suite(
    conn: sqlite3.Connection,
    agent: Agent,
    judge_client: openai.OpenAI,
    judge_model: str,
    case_ids: Optional[list[int]] = None,
) -> dict[str, Any]:
    """Runs every eval_cases row (or a subset by id), records an eval_runs row,
    and returns {run_id, results: [...]}."""
    cases = queries.list_eval_cases(conn)
    if case_ids:
        cases = [c for c in cases if c["id"] in case_ids]

    run_id = uuid.uuid4().hex
    conn.execute("INSERT INTO eval_runs (id, model) VALUES (?, ?)", (run_id, agent.model))
    results = [run_eval_case(conn, agent, judge_client, judge_model, case, run_id) for case in cases]
    conn.execute(
        "UPDATE eval_runs SET ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?", (run_id,)
    )
    return {"run_id": run_id, "results": results}


def add_eval_case(
    conn: sqlite3.Connection,
    name: str,
    input_text: str,
    rubric: str,
    expect_tools: Optional[list[str]] = None,
) -> None:
    conn.execute(
        "INSERT INTO eval_cases (name, input, rubric, expect_tools) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET input = excluded.input, rubric = excluded.rubric, "
        "expect_tools = excluded.expect_tools",
        (name, input_text, rubric, json.dumps(expect_tools) if expect_tools else None),
    )
