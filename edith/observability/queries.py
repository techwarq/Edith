"""Read-side aggregation queries over the traces/spans tables — backs the
observability API's spending/performance endpoints. Pure SQL against the
same SQLite connection everything else in edith uses (see edith/memory/db.py
SCHEMA) — no separate warehouse/analytics DB.
"""

import json
import sqlite3
from typing import Any, Optional


def _since_clause(days: Optional[int], column: str = "started_at") -> tuple[str, tuple]:
    if days is None:
        return "", ()
    return f"AND {column} >= datetime('now', ?)", (f"-{days} days",)


def spending_totals(conn: sqlite3.Connection, days: Optional[int] = None) -> dict[str, Any]:
    clause, params = _since_clause(days)
    row = conn.execute(
        f"SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd, "
        f"COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
        f"COALESCE(SUM(completion_tokens), 0) AS completion_tokens, "
        f"COUNT(*) AS trace_count "
        f"FROM traces WHERE kind = 'turn' {clause}",
        params,
    ).fetchone()
    return dict(row)


def spending_by_day(conn: sqlite3.Connection, days: int = 30) -> list[dict[str, Any]]:
    clause, params = _since_clause(days)
    rows = conn.execute(
        f"SELECT substr(started_at, 1, 10) AS date, "
        f"COALESCE(SUM(cost_usd), 0) AS cost_usd, "
        f"COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
        f"COALESCE(SUM(completion_tokens), 0) AS completion_tokens, "
        f"COUNT(*) AS trace_count "
        f"FROM traces WHERE kind = 'turn' {clause} "
        f"GROUP BY date ORDER BY date ASC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def spending_by_model(conn: sqlite3.Connection, days: Optional[int] = 30) -> list[dict[str, Any]]:
    clause, params = _since_clause(days)
    rows = conn.execute(
        f"SELECT name AS model, "
        f"COALESCE(SUM(cost_usd), 0) AS cost_usd, "
        f"COUNT(*) AS calls, "
        f"COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
        f"COALESCE(SUM(completion_tokens), 0) AS completion_tokens "
        f"FROM spans WHERE kind = 'llm' {clause} "
        f"GROUP BY name ORDER BY cost_usd DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def spending_by_session(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT session_id, COALESCE(SUM(cost_usd), 0) AS cost_usd, COUNT(*) AS trace_count, "
        "MAX(started_at) AS last_active "
        "FROM traces WHERE kind = 'turn' AND session_id IS NOT NULL "
        "GROUP BY session_id ORDER BY last_active DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_traces(
    conn: sqlite3.Connection,
    session_id: Optional[str] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    rows = conn.execute(
        f"SELECT t.id, t.session_id, t.kind, t.status, t.error, t.started_at, t.ended_at, t.duration_ms, "
        f"t.prompt_tokens, t.completion_tokens, t.cost_usd, "
        f"substr(t.input, 1, 200) AS input_preview, substr(t.output, 1, 200) AS output_preview, "
        f"(SELECT GROUP_CONCAT(DISTINCT s.name) FROM spans s WHERE s.trace_id = t.id AND s.kind = 'tool') AS tools_used "
        f"FROM traces t {where} ORDER BY t.started_at DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["tools_used"] = d["tools_used"].split(",") if d["tools_used"] else []
        results.append(d)
    return results


def get_trace(conn: sqlite3.Connection, trace_id: str) -> Optional[dict[str, Any]]:
    trace_row = conn.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()
    if trace_row is None:
        return None
    span_rows = conn.execute(
        "SELECT * FROM spans WHERE trace_id = ? ORDER BY id ASC", (trace_id,)
    ).fetchall()
    trace = dict(trace_row)
    trace["spans"] = [dict(r) for r in span_rows]
    return trace


def tool_stats(conn: sqlite3.Connection, days: Optional[int] = 30) -> list[dict[str, Any]]:
    clause, params = _since_clause(days)
    rows = conn.execute(
        f"SELECT name AS tool_name, COUNT(*) AS calls, "
        f"SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors, "
        f"AVG(duration_ms) AS avg_duration_ms "
        f"FROM spans WHERE kind = 'tool' {clause} "
        f"GROUP BY name ORDER BY calls DESC",
        params,
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["error_rate"] = (d["errors"] / d["calls"]) if d["calls"] else 0.0
        result.append(d)
    return result


def performance_overview(conn: sqlite3.Connection, days: int = 7) -> dict[str, Any]:
    clause, params = _since_clause(days)
    row = conn.execute(
        f"SELECT COUNT(*) AS turn_count, "
        f"SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count, "
        f"AVG(duration_ms) AS avg_duration_ms, "
        f"AVG(cost_usd) AS avg_cost_usd "
        f"FROM traces WHERE kind = 'turn' {clause}",
        params,
    ).fetchone()
    result = dict(row)
    turn_count = result["turn_count"] or 0
    result["error_rate"] = (result["error_count"] / turn_count) if turn_count else 0.0

    tool_clause, tool_params = _since_clause(days)
    tool_row = conn.execute(
        f"SELECT COUNT(*) AS tool_calls FROM spans WHERE kind = 'tool' {tool_clause}",
        tool_params,
    ).fetchone()
    result["avg_tool_calls_per_turn"] = (tool_row["tool_calls"] / turn_count) if turn_count else 0.0
    return result


def performance_trend(conn: sqlite3.Connection, days: int = 30) -> list[dict[str, Any]]:
    """Daily error rate / latency / cost / context-size / tool-trajectory
    health, oldest -> newest — the actual "is it getting better or worse"
    series that performance_overview's single-window average can't show (two
    quiet weeks then one bad day look identical in an average; they don't in
    a trend).

    avg_prompt_tokens, tool_hallucination_rate, and redundant_tool_call_rate
    are early-warning signals a plain error-rate/latency view misses:
    - avg_prompt_tokens climbing over time is the leading indicator behind
      the 2026-07-28 blank-reply bug class (a big context left less budget
      for the actual answer) — worth watching even when nothing's erroring.
    - tool_hallucination_rate: turns where the model called a tool name that
      doesn't exist in the registry (ToolRegistry.dispatch's "ERROR: unknown
      tool" reply), not just a tool that ran and failed.
    - redundant_tool_call_rate: the same (tool, args) pair called more than
      once within a single turn — wasted latency/cost with no new signal.
    """
    clause, params = _since_clause(days)
    rows = conn.execute(
        f"SELECT substr(started_at, 1, 10) AS date, "
        f"COUNT(*) AS turn_count, "
        f"SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count, "
        f"AVG(duration_ms) AS avg_duration_ms, "
        f"AVG(cost_usd) AS avg_cost_usd, "
        f"AVG(prompt_tokens) AS avg_prompt_tokens "
        f"FROM traces WHERE kind = 'turn' {clause} "
        f"GROUP BY date ORDER BY date ASC",
        params,
    ).fetchall()
    by_day = {r["date"]: dict(r) for r in rows}
    for d in by_day.values():
        d["error_rate"] = (d["error_count"] / d["turn_count"]) if d["turn_count"] else 0.0

    for date, stats in _tool_trajectory_stats_by_day(conn, days).items():
        if date in by_day:
            turn_count = by_day[date]["turn_count"]
            by_day[date]["avg_tool_calls_per_turn"] = (stats["tool_calls"] / turn_count) if turn_count else 0.0
            by_day[date]["tool_hallucination_rate"] = (
                (stats["hallucinated"] / stats["tool_calls"]) if stats["tool_calls"] else 0.0
            )
            by_day[date]["redundant_tool_call_rate"] = (
                (stats["redundant"] / stats["tool_calls"]) if stats["tool_calls"] else 0.0
            )
    for d in by_day.values():
        d.setdefault("avg_tool_calls_per_turn", 0.0)
        d.setdefault("tool_hallucination_rate", 0.0)
        d.setdefault("redundant_tool_call_rate", 0.0)

    return sorted(by_day.values(), key=lambda d: d["date"])


def _tool_trajectory_stats_by_day(conn: sqlite3.Connection, days: Optional[int]) -> dict[str, dict[str, int]]:
    """Per-day tool-call/hallucination/redundant-call counts. Done in Python,
    not SQL, because "redundant" requires de-duplicating (trace_id, name,
    input) as we go — awkward to express as a single aggregate query, and
    this dataset (one personal user's tool calls) is small enough that it
    doesn't matter."""
    clause, params = _since_clause(days, column="t.started_at")
    rows = conn.execute(
        f"SELECT substr(t.started_at, 1, 10) AS date, s.trace_id, s.name, s.input, s.error "
        f"FROM spans s JOIN traces t ON t.id = s.trace_id "
        f"WHERE s.kind = 'tool' AND t.kind = 'turn' {clause}",
        params,
    ).fetchall()

    by_day: dict[str, dict[str, int]] = {}
    seen_calls: dict[str, set] = {}
    for r in rows:
        date, trace_id = r["date"], r["trace_id"]
        stats = by_day.setdefault(date, {"tool_calls": 0, "hallucinated": 0, "redundant": 0})
        stats["tool_calls"] += 1
        if r["error"] and r["error"].startswith("ERROR: unknown tool"):
            stats["hallucinated"] += 1
        seen = seen_calls.setdefault(trace_id, set())
        key = (r["name"], r["input"])
        if key in seen:
            stats["redundant"] += 1
        else:
            seen.add(key)
    return by_day


# ---------------------------------------------------------------------------
# evals
# ---------------------------------------------------------------------------

def list_eval_cases(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, name, input, rubric, expect_tools, created_at FROM eval_cases ORDER BY id ASC"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["expect_tools"] = json.loads(d["expect_tools"]) if d["expect_tools"] else []
        result.append(d)
    return result


def list_eval_runs(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT er.id, er.model, er.started_at, er.ended_at, "
        "COUNT(res.id) AS case_count, "
        "COALESCE(AVG(res.score), 0) AS avg_score, "
        "SUM(CASE WHEN res.passed THEN 1 ELSE 0 END) AS passed_count "
        "FROM eval_runs er LEFT JOIN eval_results res ON res.run_id = er.id "
        "GROUP BY er.id ORDER BY er.started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def eval_run_trend(conn: sqlite3.Connection, limit: int = 30) -> list[dict[str, Any]]:
    """Same shape as list_eval_runs, oldest -> newest, capped to the most
    recent `limit` runs — what the score-over-time chart plots. Includes
    `model` per run so a quality change lines up against a model switch."""
    rows = conn.execute(
        "SELECT * FROM ("
        "  SELECT er.id, er.model, er.started_at, er.ended_at, "
        "  COUNT(res.id) AS case_count, "
        "  COALESCE(AVG(res.score), 0) AS avg_score, "
        "  SUM(CASE WHEN res.passed THEN 1 ELSE 0 END) AS passed_count "
        "  FROM eval_runs er LEFT JOIN eval_results res ON res.run_id = er.id "
        "  WHERE er.ended_at IS NOT NULL "
        "  GROUP BY er.id ORDER BY er.started_at DESC LIMIT ?"
        ") ORDER BY started_at ASC",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def eval_case_trend(conn: sqlite3.Connection, case_id: int, limit: int = 30) -> list[dict[str, Any]]:
    """One eval case's score/pass history across runs, oldest -> newest —
    catches a regression specific to one behavior that a suite-wide average
    would dilute away."""
    rows = conn.execute(
        "SELECT * FROM ("
        "  SELECT res.score, res.passed, res.created_at, er.model "
        "  FROM eval_results res JOIN eval_runs er ON er.id = res.run_id "
        "  WHERE res.case_id = ? ORDER BY res.created_at DESC LIMIT ?"
        ") ORDER BY created_at ASC",
        (case_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_eval_run(conn: sqlite3.Connection, run_id: str) -> Optional[dict[str, Any]]:
    run_row = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    if run_row is None:
        return None
    result_rows = conn.execute(
        "SELECT res.*, ec.name AS case_name, ec.input AS case_input, ec.rubric AS case_rubric "
        "FROM eval_results res JOIN eval_cases ec ON ec.id = res.case_id "
        "WHERE res.run_id = ? ORDER BY res.id ASC",
        (run_id,),
    ).fetchall()
    run = dict(run_row)
    results = []
    for r in result_rows:
        d = dict(r)
        d["tools_called"] = json.loads(d["tools_called"]) if d["tools_called"] else []
        results.append(d)
    run["results"] = results
    return run
