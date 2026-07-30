"""Tests for edith/observability/api.py — builds a standalone FastAPI app
around build_router() with a fake conn/agent/judge (never touches server.py,
which builds a real AppContext at import time and needs live credentials)."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from edith.memory import db
from edith.observability import api as observability_api
from edith.observability.tracing import Recorder

TOKEN = "test-token"


class _FakeAgent:
    model = "gemini-3.5-flash"

    def __init__(self, conn):
        self.conn = conn

    def handle_turn(self, session_id, text):
        recorder = Recorder(self.conn, session_id, kind="turn", input_text=text)
        recorder.finish("a reply")
        return "a reply"


class _FakeJudgeClient:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                class _Msg:
                    content = json.dumps({"score": 0.9, "passed": True, "reasoning": "fine"})

                class _Choice:
                    message = _Msg()

                class _Resp:
                    choices = [_Choice()]

                return _Resp()


def _client(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    conn.execute("INSERT INTO sessions (id, model) VALUES ('s1', 'gemini-3.5-flash')")
    agent = _FakeAgent(conn)
    router = observability_api.build_router(conn, agent, _FakeJudgeClient(), "judge-model", TOKEN)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), conn


def test_spending_requires_token(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/observability/spending")
    assert resp.status_code == 401


def test_spending_returns_totals(tmp_path):
    client, conn = _client(tmp_path)
    recorder = Recorder(conn, "s1", input_text="hi")
    recorder.record_llm_span("gemini-3.5-flash", 100, 50, "reply", 10.0)
    recorder.finish("final")

    resp = client.get("/api/observability/spending", params={"token": TOKEN})

    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["trace_count"] == 1
    assert body["totals"]["prompt_tokens"] == 100


def test_list_and_get_trace(tmp_path):
    client, conn = _client(tmp_path)
    recorder = Recorder(conn, "s1", input_text="hi")
    recorder.record_tool_span("web_search", {"query": "x"}, "results", 5.0)
    trace_id = recorder.finish("final")

    list_resp = client.get("/api/observability/traces", params={"token": TOKEN})
    assert list_resp.status_code == 200
    assert len(list_resp.json()["traces"]) == 1

    get_resp = client.get(f"/api/observability/traces/{trace_id}", params={"token": TOKEN})
    assert get_resp.status_code == 200
    assert len(get_resp.json()["spans"]) == 1

    missing_resp = client.get("/api/observability/traces/does-not-exist", params={"token": TOKEN})
    assert missing_resp.status_code == 404


def test_performance_and_tools_endpoints(tmp_path):
    client, conn = _client(tmp_path)
    recorder = Recorder(conn, "s1", input_text="hi")
    recorder.record_tool_span("web_search", {}, "ok", 5.0)
    recorder.finish("final")

    perf_resp = client.get("/api/observability/performance", params={"token": TOKEN})
    assert perf_resp.status_code == 200
    assert perf_resp.json()["turn_count"] == 1

    tools_resp = client.get("/api/observability/tools", params={"token": TOKEN})
    assert tools_resp.status_code == 200
    assert tools_resp.json()["tools"][0]["tool_name"] == "web_search"


def test_evals_run_end_to_end(tmp_path):
    client, conn = _client(tmp_path)
    conn.execute(
        "INSERT INTO eval_cases (name, input, rubric) VALUES ('c1', 'input', 'rubric')"
    )

    cases_resp = client.get("/api/observability/evals/cases", params={"token": TOKEN})
    assert len(cases_resp.json()["cases"]) == 1

    run_resp = client.post("/api/observability/evals/run", json={"token": TOKEN})
    assert run_resp.status_code == 200
    run_body = run_resp.json()
    assert len(run_body["results"]) == 1
    run_id = run_body["run_id"]

    runs_resp = client.get("/api/observability/evals/runs", params={"token": TOKEN})
    assert runs_resp.status_code == 200
    assert runs_resp.json()["runs"][0]["case_count"] == 1

    run_detail_resp = client.get(f"/api/observability/evals/runs/{run_id}", params={"token": TOKEN})
    assert run_detail_resp.status_code == 200
    assert run_detail_resp.json()["results"][0]["case_name"] == "c1"


def test_evals_run_rejects_bad_token(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/api/observability/evals/run", json={"token": "wrong"})
    assert resp.status_code == 401
