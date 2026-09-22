import json

from edith.memory import db, store
from edith.observability import evals


def _conn(tmp_path):
    return db.connect(tmp_path / "test.db")


class _FakeAgent:
    """Stands in for edith.agent.Agent — handle_turn writes a real trace via
    Recorder (like the real agent does) so evals can find it afterwards, but
    never calls a real LLM."""

    def __init__(self, conn, model="gemini-3.5-flash", reply="a helpful reply", tool_calls=None):
        self.conn = conn
        self.model = model
        self.reply = reply
        self.tool_calls = tool_calls or []

    def handle_turn(self, session_id, text):
        from edith.observability.tracing import Recorder

        recorder = Recorder(self.conn, session_id, kind="turn", input_text=text)
        for tool in self.tool_calls:
            recorder.record_tool_span(tool, {}, "ok", 5.0)
        recorder.finish(self.reply)
        return self.reply


class _FakeJudgeClient:
    def __init__(self, response_json):
        self.response_json = response_json
        self.calls = []

        class _Chat:
            def __init__(self, outer):
                self.completions = self

            def create(_inner_self, **kwargs):
                self.calls.append(kwargs)

                class _Msg:
                    content = json.dumps(self.response_json)

                class _Choice:
                    message = _Msg()

                class _Resp:
                    choices = [_Choice()]

                return _Resp()

        self.chat = _Chat(self)


def _make_case(conn, name="case1", expect_tools=None):
    conn.execute(
        "INSERT INTO eval_cases (name, input, rubric, expect_tools) VALUES (?, ?, ?, ?)",
        (name, "some input", "some rubric", json.dumps(expect_tools) if expect_tools else None),
    )
    row = conn.execute("SELECT * FROM eval_cases WHERE name = ?", (name,)).fetchone()
    return {"id": row["id"], "name": name, "input": "some input", "rubric": "some rubric", "expect_tools": expect_tools or []}


def _make_run(conn, run_id="run1"):
    conn.execute("INSERT INTO eval_runs (id, model) VALUES (?, 'gemini-3.5-flash')", (run_id,))
    return run_id


def test_run_eval_case_records_result(tmp_path):
    conn = _conn(tmp_path)
    case = _make_case(conn)
    _make_run(conn)
    agent = _FakeAgent(conn, reply="here is a great answer")
    judge = _FakeJudgeClient({"score": 0.9, "passed": True, "reasoning": "great"})

    result = evals.run_eval_case(conn, agent, judge, "judge-model", case, run_id="run1")

    assert result["score"] == 0.9
    assert result["passed"] is True
    assert result["trace_id"] is not None

    row = conn.execute("SELECT * FROM eval_results WHERE run_id = 'run1'").fetchone()
    assert row["score"] == 0.9
    assert row["passed"] == 1


def test_run_eval_case_fails_when_expected_tool_not_called(tmp_path):
    conn = _conn(tmp_path)
    case = _make_case(conn, expect_tools=["web_search"])
    _make_run(conn)
    agent = _FakeAgent(conn, reply="I think the answer is X", tool_calls=[])
    judge = _FakeJudgeClient({"score": 0.95, "passed": True, "reasoning": "sounds confident"})

    result = evals.run_eval_case(conn, agent, judge, "judge-model", case, run_id="run1")

    assert result["passed"] is False
    assert "web_search" in result["reasoning"]


def test_run_eval_case_passes_when_expected_tool_called(tmp_path):
    conn = _conn(tmp_path)
    case = _make_case(conn, expect_tools=["web_search"])
    _make_run(conn)
    agent = _FakeAgent(conn, reply="grounded answer", tool_calls=["web_search"])
    judge = _FakeJudgeClient({"score": 0.85, "passed": True, "reasoning": "grounded"})

    result = evals.run_eval_case(conn, agent, judge, "judge-model", case, run_id="run1")

    assert result["passed"] is True
    assert result["tools_called"] == ["web_search"]


def test_run_eval_case_handles_malformed_judge_response(tmp_path):
    conn = _conn(tmp_path)
    case = _make_case(conn)
    _make_run(conn)
    agent = _FakeAgent(conn)

    class _BrokenJudge:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("upstream 500")

    result = evals.run_eval_case(conn, agent, _BrokenJudge(), "judge-model", case, run_id="run1")

    assert result["score"] == 0.0
    assert result["passed"] is False
    assert "judge error" in result["reasoning"]


def test_run_eval_suite_runs_all_cases_and_creates_run(tmp_path):
    conn = _conn(tmp_path)
    _make_case(conn, name="case1")
    _make_case(conn, name="case2")
    agent = _FakeAgent(conn)
    judge = _FakeJudgeClient({"score": 0.8, "passed": True, "reasoning": "fine"})

    outcome = evals.run_eval_suite(conn, agent, judge, "judge-model")

    assert len(outcome["results"]) == 2
    run_row = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (outcome["run_id"],)).fetchone()
    assert run_row["ended_at"] is not None


def test_run_eval_case_uses_scratch_session_not_interactive_one(tmp_path):
    conn = _conn(tmp_path)
    real_session = store.create_session(conn, "gemini-3.5-flash")
    store.set_meta(conn, "last_session_id", real_session)
    case = _make_case(conn)
    _make_run(conn)
    agent = _FakeAgent(conn)
    judge = _FakeJudgeClient({"score": 0.7, "passed": True, "reasoning": "ok"})

    evals.run_eval_case(conn, agent, judge, "judge-model", case, run_id="run1")

    messages = conn.execute("SELECT * FROM messages WHERE session_id = ?", (real_session,)).fetchall()
    assert messages == []
