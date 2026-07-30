"""Tests for the interface-agnostic slash-command dispatcher (edith/commands.py),
shared by cli.py and server.py. Every command is synchronous request -> text
response with no blocking prompts — including /approve, which takes an
explicit action id rather than the old interactive per-item y/n loop.
"""

import pytest

from edith import commands
from edith.config import Settings
from edith.google.auth import GoogleAuthError
from edith.memory import db, store


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        api_key="test-key",
        model="test-model",
        gemini_api_key="test-gemini-key",
        gemini_grounding_model="test-gemini-grounding-model",
        openrouter_text_model="test-openrouter-model",
        db_path=tmp_path / "edith.db",
        log_path=tmp_path / "edith.log",
        history_path=tmp_path / "history",
        stt_model="test-stt",
        tts_model="test-tts",
        tts_voice="Eve",
        temporal_address="",
        temporal_namespace="",
        temporal_api_key="",
        temporal_task_queue="test-task-queue",
        nightly_reflection_cron="0 3 * * *",
        qdrant_url="",
        qdrant_api_key="",
        firebase_service_account_json="",
        hunter_api_key="",
    )


def test_exit_returns_none_session_id(conn, settings):
    session_id, voice_enabled, output = commands.handle_command(
        "/exit", conn, settings, "sid", agent=None, voice_enabled=False
    )
    assert session_id is None


def test_voice_toggle(conn, settings):
    session_id, voice_enabled, output = commands.handle_command(
        "/voice on", conn, settings, "sid", agent=None, voice_enabled=False
    )
    assert voice_enabled is True
    assert "enabled" in output

    session_id, voice_enabled, output = commands.handle_command(
        "/voice off", conn, settings, "sid", agent=None, voice_enabled=True
    )
    assert voice_enabled is False
    assert "disabled" in output


def test_voice_toggle_bad_arg(conn, settings):
    _, voice_enabled, output = commands.handle_command(
        "/voice sideways", conn, settings, "sid", agent=None, voice_enabled=False
    )
    assert voice_enabled is False
    assert "Usage" in output


def test_new_session(conn, settings):
    sid = store.create_session(conn, settings.model)
    new_id, _, output = commands.handle_command("/new", conn, settings, sid, agent=None, voice_enabled=False)
    assert new_id != sid
    assert new_id[:8] in output


def test_facts_empty(conn, settings):
    _, _, output = commands.handle_command("/facts", conn, settings, "sid", agent=None, voice_enabled=False)
    assert "No facts" in output


def test_facts_lists_stored(conn, settings):
    store.save_fact(conn, "role", "PM", category="identity")
    _, _, output = commands.handle_command("/facts", conn, settings, "sid", agent=None, voice_enabled=False)
    assert "role: PM" in output


def test_history_no_query(conn, settings):
    _, _, output = commands.handle_command("/history", conn, settings, "sid", agent=None, voice_enabled=False)
    assert "Usage" in output


def test_history_search(conn, settings):
    sid = store.create_session(conn, settings.model)
    store.add_message(conn, sid, "user", content="I love hiking")
    _, _, output = commands.handle_command("/history hiking", conn, settings, sid, agent=None, voice_enabled=False)
    assert "hiking" in output


def test_google_login_success(monkeypatch, conn, settings):
    monkeypatch.setattr(commands.google_auth, "run_login_flow", lambda: None)
    _, _, output = commands.handle_command("/google login", conn, settings, "sid", agent=None, voice_enabled=False)
    assert output == "Google account connected."


def test_google_login_missing_client_secret(monkeypatch, conn, settings):
    def raise_auth_error():
        raise GoogleAuthError("No client secret found")

    monkeypatch.setattr(commands.google_auth, "run_login_flow", raise_auth_error)
    _, _, output = commands.handle_command("/google login", conn, settings, "sid", agent=None, voice_enabled=False)
    assert "No client secret found" in output


def test_approve_no_pending_actions(conn, settings):
    _, _, output = commands.handle_command("/approve", conn, settings, "sid", agent=None, voice_enabled=False)
    assert "No pending actions" in output


def test_approve_no_arg_lists_pending(conn, settings):
    store.queue_pending_action(conn, "send_email", {"to": "x@y.com"}, "Send email to x@y.com")
    _, _, output = commands.handle_command("/approve", conn, settings, "sid", agent=None, voice_enabled=False)
    assert "send_email" in output
    assert "Send email to x@y.com" in output
    assert "/approve <id>" in output


def test_approve_bad_id_format(conn, settings):
    _, _, output = commands.handle_command("/approve abc", conn, settings, "sid", agent=None, voice_enabled=False)
    assert "Usage" in output


def test_approve_unknown_id(conn, settings):
    _, _, output = commands.handle_command("/approve 999", conn, settings, "sid", agent=None, voice_enabled=False)
    assert "No pending action with id 999" in output


def test_approve_executes_and_marks_approved(monkeypatch, conn, settings):
    action_id = store.queue_pending_action(conn, "send_email", {"to": "x@y.com"}, "Send email to x@y.com")
    monkeypatch.setattr(commands.google_auth, "get_credentials", lambda: object())

    calls = []
    monkeypatch.setitem(commands.EXECUTORS, "send_email", lambda creds, args: calls.append(args) or "Email sent.")

    _, _, output = commands.handle_command(f"/approve {action_id}", conn, settings, "sid", agent=None, voice_enabled=False)

    assert calls == [{"to": "x@y.com"}]
    assert output == "Email sent."
    assert store.get_pending_actions(conn, status="pending") == []
    assert len(store.get_pending_actions(conn, status="approved")) == 1


def test_reject_does_not_execute(monkeypatch, conn, settings):
    action_id = store.queue_pending_action(conn, "send_email", {"to": "x@y.com"}, "Send email to x@y.com")

    calls = []
    monkeypatch.setitem(commands.EXECUTORS, "send_email", lambda creds, args: calls.append(args) or "Email sent.")

    _, _, output = commands.handle_command(f"/reject {action_id}", conn, settings, "sid", agent=None, voice_enabled=False)

    assert calls == []
    assert f"Rejected action #{action_id}" in output
    assert len(store.get_pending_actions(conn, status="rejected")) == 1


def test_approve_whatsapp_action_unaffected_by_missing_google_auth(monkeypatch, conn, settings):
    action_id = store.queue_pending_action(
        conn, "send_whatsapp_message", {"chat_name": "Mom", "message": "hi"}, "Send to Mom"
    )
    monkeypatch.setattr(commands.google_auth, "get_credentials", lambda: None)

    calls = []
    monkeypatch.setitem(
        commands.EXECUTORS, "send_whatsapp_message", lambda auth, args: calls.append((auth, args)) or "Message sent."
    )

    _, _, output = commands.handle_command(f"/approve {action_id}", conn, settings, "sid", agent=None, voice_enabled=False)

    assert calls == [(None, {"chat_name": "Mom", "message": "hi"})]
    assert output == "Message sent."


def test_unknown_command(conn, settings):
    _, _, output = commands.handle_command("/bogus", conn, settings, "sid", agent=None, voice_enabled=False)
    assert "Unknown command" in output
