from edith.memory import db
from edith.observability.tracing import Recorder


def _conn(tmp_path):
    return db.connect(tmp_path / "test.db")


def test_recorder_creates_trace_row_on_construction(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("INSERT INTO sessions (id, model) VALUES ('s1', 'gemini-3.5-flash')")

    recorder = Recorder(conn, "s1", kind="turn", input_text="hello")

    row = conn.execute("SELECT * FROM traces WHERE id = ?", (recorder.trace_id,)).fetchone()
    assert row["session_id"] == "s1"
    assert row["kind"] == "turn"
    assert row["input"] == "hello"
    assert row["status"] == "ok"


def test_record_llm_span_accumulates_cost_and_tokens(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("INSERT INTO sessions (id, model) VALUES ('s1', 'gemini-3.5-flash')")
    recorder = Recorder(conn, "s1", input_text="hi")

    recorder.record_llm_span("gemini-3.5-flash", 1000, 500, "partial reply", 42.0)
    recorder.record_llm_span("gemini-3.5-flash", 200, 100, "final reply", 10.0)

    assert recorder.prompt_tokens == 1200
    assert recorder.completion_tokens == 600
    assert recorder.cost_usd > 0

    spans = conn.execute("SELECT * FROM spans WHERE trace_id = ? ORDER BY id", (recorder.trace_id,)).fetchall()
    assert len(spans) == 2
    assert spans[0]["kind"] == "llm"
    assert spans[0]["name"] == "gemini-3.5-flash"
    assert spans[0]["prompt_tokens"] == 1000


def test_record_tool_span_error_status(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("INSERT INTO sessions (id, model) VALUES ('s1', 'gemini-3.5-flash')")
    recorder = Recorder(conn, "s1", input_text="search my email")

    recorder.record_tool_span("gmail_search", {"query": "invoices"}, "ERROR: not connected", 5.0, status="error", error="not connected")

    span = conn.execute("SELECT * FROM spans WHERE trace_id = ?", (recorder.trace_id,)).fetchone()
    assert span["kind"] == "tool"
    assert span["name"] == "gmail_search"
    assert span["status"] == "error"
    assert span["error"] == "not connected"


def test_finish_writes_totals_and_output(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("INSERT INTO sessions (id, model) VALUES ('s1', 'gemini-3.5-flash')")
    recorder = Recorder(conn, "s1", input_text="hi")
    recorder.record_llm_span("gemini-3.5-flash", 100, 50, "reply", 12.0)

    trace_id = recorder.finish("final answer")

    row = conn.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()
    assert row["output"] == "final answer"
    assert row["status"] == "ok"
    assert row["prompt_tokens"] == 100
    assert row["completion_tokens"] == 50
    assert row["cost_usd"] > 0
    assert row["ended_at"] is not None
    assert row["duration_ms"] is not None


def test_finish_records_error_status(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("INSERT INTO sessions (id, model) VALUES ('s1', 'gemini-3.5-flash')")
    recorder = Recorder(conn, "s1", input_text="hi")

    trace_id = recorder.finish("Sorry, error", status="error", error="context_length_exceeded")

    row = conn.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()
    assert row["status"] == "error"
    assert row["error"] == "context_length_exceeded"


def test_input_output_are_truncated(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("INSERT INTO sessions (id, model) VALUES ('s1', 'gemini-3.5-flash')")
    huge = "x" * 10_000
    recorder = Recorder(conn, "s1", input_text=huge)

    row = conn.execute("SELECT input FROM traces WHERE id = ?", (recorder.trace_id,)).fetchone()
    assert len(row["input"]) < 10_000
    assert row["input"].endswith("…(truncated)")
