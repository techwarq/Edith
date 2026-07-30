import pytest

from edith.memory import db, search, store


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_create_and_resume_session(conn):
    sid = store.create_session(conn, "test-model")
    assert store.get_last_session_id(conn) == sid
    assert store.session_exists(conn, sid)
    assert store.any_session_exists(conn)


def test_save_update_forget_fact(conn):
    store.save_fact(conn, "role", "PM", category="identity")
    assert store.get_fact(conn, "role") == "PM"

    store.save_fact(conn, "role", "Senior PM", category="identity")  # upsert
    assert store.get_fact(conn, "role") == "Senior PM"
    assert len(store.get_all_facts(conn)) == 1

    assert store.forget_fact(conn, "role") is True
    assert store.get_fact(conn, "role") is None
    assert store.forget_fact(conn, "role") is False


def test_working_messages_whole_turn_trimming(conn):
    sid = store.create_session(conn, "test-model")
    for i in range(5):
        store.add_message(conn, sid, "user", content=f"user msg {i}")
        store.add_message(conn, sid, "assistant", content=f"assistant reply {i}")

    trimmed = store.get_working_messages(conn, sid, max_turns=2)
    # last 2 turns = 4 messages
    assert len(trimmed) == 4
    assert trimmed[0]["content"] == "user msg 3"
    assert trimmed[-1]["content"] == "assistant reply 4"


def test_working_messages_preserves_tool_call_pairing(conn):
    sid = store.create_session(conn, "test-model")
    store.add_message(conn, sid, "user", content="what's the weather")
    store.add_message(
        conn,
        sid,
        "assistant",
        content=None,
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}],
    )
    store.add_message(conn, sid, "tool", content="sunny", tool_call_id="call_1", tool_name="web_search")
    store.add_message(conn, sid, "assistant", content="It's sunny.")

    trimmed = store.get_working_messages(conn, sid, max_turns=1)
    assert len(trimmed) == 4
    assert trimmed[1]["tool_calls"][0]["id"] == "call_1"
    assert trimmed[2]["tool_call_id"] == "call_1"


def test_search_history_finds_message(conn):
    sid = store.create_session(conn, "test-model")
    store.add_message(conn, sid, "user", content="I love hiking in the mountains")
    store.add_message(conn, sid, "assistant", content="Noted!")

    results = search.search_history(conn, "hiking")
    assert any("hiking" in r["content"] for r in results)


def test_search_history_escapes_special_chars(conn):
    sid = store.create_session(conn, "test-model")
    store.add_message(conn, sid, "user", content="AND OR NOT are FTS5 keywords")
    # should not raise a syntax error even though query contains FTS operators
    results = search.search_history(conn, "AND OR NOT")
    assert isinstance(results, list)


def test_queue_and_get_pending_actions(conn):
    action_id = store.queue_pending_action(
        conn, tool_name="send_email", args={"to": "x@y.com"}, preview="Send email to x@y.com"
    )
    pending = store.get_pending_actions(conn)
    assert len(pending) == 1
    assert pending[0]["id"] == action_id
    assert pending[0]["tool_name"] == "send_email"
    assert pending[0]["args"] == {"to": "x@y.com"}
    assert pending[0]["status"] == "pending"


def test_resolve_pending_action_approved(conn):
    action_id = store.queue_pending_action(conn, "send_email", {"to": "x@y.com"}, "preview")
    resolved = store.resolve_pending_action(conn, action_id, "approved")
    assert resolved["tool_name"] == "send_email"
    assert resolved["args"] == {"to": "x@y.com"}
    assert store.get_pending_actions(conn, status="pending") == []
    assert len(store.get_pending_actions(conn, status="approved")) == 1


def test_get_facts_by_category(conn):
    store.save_fact(conn, "https://a.example", "site A", category="tracked_url")
    store.save_fact(conn, "https://b.example", "site B", category="tracked_url")
    store.save_fact(conn, "role", "PM", category="identity")

    tracked = store.get_facts_by_category(conn, "tracked_url")
    assert {f["key"] for f in tracked} == {"https://a.example", "https://b.example"}
    assert store.get_facts_by_category(conn, "nonexistent") == []


def test_get_or_create_jobs_session_is_stable_and_separate_from_last_session(conn):
    interactive_sid = store.create_session(conn, "test-model")
    jobs_sid = store.get_or_create_jobs_session(conn, "test-model")

    assert jobs_sid != interactive_sid
    # must not have clobbered last_session_id — get_or_create_jobs_session is called
    # from a background worker process, not the interactive CLI/server session
    assert store.get_last_session_id(conn) == interactive_sid
    # idempotent — same session reused on subsequent calls
    assert store.get_or_create_jobs_session(conn, "test-model") == jobs_sid


def test_get_recent_assistant_replies(conn):
    sid = store.get_or_create_jobs_session(conn, "test-model")
    store.add_message(conn, sid, "user", content="run reflection")
    store.add_message(conn, sid, "assistant", content="digest 1")
    store.add_message(conn, sid, "assistant", content="digest 2")

    replies = store.get_recent_assistant_replies(conn, sid, limit=10)
    assert [r["content"] for r in replies] == ["digest 2", "digest 1"]


def test_resolve_pending_action_already_resolved_returns_none(conn):
    action_id = store.queue_pending_action(conn, "send_email", {}, "preview")
    store.resolve_pending_action(conn, action_id, "rejected")
    assert store.resolve_pending_action(conn, action_id, "approved") is None


def test_resolve_pending_action_unknown_id_returns_none(conn):
    assert store.resolve_pending_action(conn, 9999, "approved") is None
