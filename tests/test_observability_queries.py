from edith.memory import db
from edith.observability import queries
from edith.observability.tracing import Recorder


def _conn(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    conn.execute("INSERT INTO sessions (id, model) VALUES ('s1', 'gemini-3.5-flash')")
    conn.execute("INSERT INTO sessions (id, model) VALUES ('s2', 'gemini-3.5-flash')")
    return conn


def _turn(conn, session_id, model="gemini-3.5-flash", tool=None, tool_status="ok"):
    recorder = Recorder(conn, session_id, input_text="hi")
    recorder.record_llm_span(model, 1000, 500, "reply", 20.0)
    if tool:
        recorder.record_tool_span(tool, {}, "result", 5.0, status=tool_status, error=None if tool_status == "ok" else "boom")
    recorder.finish("final")
    return recorder.trace_id


def test_spending_totals_sums_across_sessions(tmp_path):
    conn = _conn(tmp_path)
    _turn(conn, "s1")
    _turn(conn, "s2")

    totals = queries.spending_totals(conn)

    assert totals["trace_count"] == 2
    assert totals["prompt_tokens"] == 2000
    assert totals["cost_usd"] > 0


def test_spending_by_model_groups_correctly(tmp_path):
    conn = _conn(tmp_path)
    _turn(conn, "s1", model="gemini-3.5-flash")
    _turn(conn, "s2", model="qwen/qwen3-coder-next")

    by_model = queries.spending_by_model(conn, days=None)

    models = {r["model"] for r in by_model}
    assert models == {"gemini-3.5-flash", "qwen/qwen3-coder-next"}
    for r in by_model:
        assert r["calls"] == 1


def test_list_traces_includes_tools_used(tmp_path):
    conn = _conn(tmp_path)
    trace_id = _turn(conn, "s1", tool="web_search")
    no_tool_trace_id = _turn(conn, "s2")

    traces = {t["id"]: t for t in queries.list_traces(conn)}

    assert traces[trace_id]["tools_used"] == ["web_search"]
    assert traces[no_tool_trace_id]["tools_used"] == []


def test_list_traces_filters_by_session(tmp_path):
    conn = _conn(tmp_path)
    _turn(conn, "s1")
    _turn(conn, "s2")

    traces = queries.list_traces(conn, session_id="s1")

    assert len(traces) == 1
    assert traces[0]["session_id"] == "s1"


def test_get_trace_includes_spans(tmp_path):
    conn = _conn(tmp_path)
    trace_id = _turn(conn, "s1", tool="web_search")

    trace = queries.get_trace(conn, trace_id)

    assert trace is not None
    kinds = {s["kind"] for s in trace["spans"]}
    assert kinds == {"llm", "tool"}


def test_get_trace_missing_returns_none(tmp_path):
    conn = _conn(tmp_path)
    assert queries.get_trace(conn, "does-not-exist") is None


def test_tool_stats_computes_error_rate(tmp_path):
    conn = _conn(tmp_path)
    _turn(conn, "s1", tool="gmail_search", tool_status="ok")
    _turn(conn, "s2", tool="gmail_search", tool_status="error")

    stats = queries.tool_stats(conn, days=None)

    assert len(stats) == 1
    assert stats[0]["tool_name"] == "gmail_search"
    assert stats[0]["calls"] == 2
    assert stats[0]["errors"] == 1
    assert stats[0]["error_rate"] == 0.5


def test_performance_overview_error_rate(tmp_path):
    conn = _conn(tmp_path)
    _turn(conn, "s1")
    recorder = Recorder(conn, "s2", input_text="broken")
    recorder.finish("oops", status="error", error="boom")

    overview = queries.performance_overview(conn, days=3650)

    assert overview["turn_count"] == 2
    assert overview["error_count"] == 1
    assert overview["error_rate"] == 0.5


def test_eval_case_and_run_roundtrip(tmp_path):
    conn = _conn(tmp_path)
    conn.execute(
        "INSERT INTO eval_cases (name, input, rubric, expect_tools) VALUES (?, ?, ?, ?)",
        ("case1", "input text", "rubric text", '["web_search"]'),
    )
    cases = queries.list_eval_cases(conn)
    assert len(cases) == 1
    assert cases[0]["expect_tools"] == ["web_search"]

    conn.execute("INSERT INTO eval_runs (id, model) VALUES ('run1', 'gemini-3.5-flash')")
    conn.execute(
        "INSERT INTO eval_results (run_id, case_id, trace_id, score, passed, judge_reasoning, tools_called) "
        "VALUES ('run1', ?, NULL, 0.9, 1, 'looks good', '[]')",
        (cases[0]["id"],),
    )

    runs = queries.list_eval_runs(conn)
    assert len(runs) == 1
    assert runs[0]["case_count"] == 1
    assert runs[0]["passed_count"] == 1

    run_detail = queries.get_eval_run(conn, "run1")
    assert run_detail is not None
    assert len(run_detail["results"]) == 1
    assert run_detail["results"][0]["case_name"] == "case1"
