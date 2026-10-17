import pytest

from edith.memory import conversation
from edith.memory.storage import sqlite


@pytest.fixture
def conn(tmp_path):
    c = sqlite.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_create_and_resume_session(conn):
    sid = conversation.create_session(conn, "test-model")
    assert conversation.get_last_session_id(conn) == sid
    assert conversation.session_exists(conn, sid)
    assert conversation.any_session_exists(conn)


def test_working_messages_whole_turn_trimming(conn):
    sid = conversation.create_session(conn, "test-model")
    for i in range(5):
        conversation.add_message(conn, sid, "user", content=f"user msg {i}")
        conversation.add_message(conn, sid, "assistant", content=f"assistant reply {i}")

    trimmed = conversation.get_working_messages(conn, sid, max_turns=2)
    # last 2 turns = 4 messages
    assert len(trimmed) == 4
    assert trimmed[0]["content"] == "user msg 3"
    assert trimmed[-1]["content"] == "assistant reply 4"


def test_working_messages_preserves_tool_call_pairing(conn):
    sid = conversation.create_session(conn, "test-model")
    conversation.add_message(conn, sid, "user", content="what's the weather")
    conversation.add_message(
        conn,
        sid,
        "assistant",
        content=None,
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}],
    )
    conversation.add_message(conn, sid, "tool", content="sunny", tool_call_id="call_1", tool_name="web_search")
    conversation.add_message(conn, sid, "assistant", content="It's sunny.")

    trimmed = conversation.get_working_messages(conn, sid, max_turns=1)
    assert len(trimmed) == 4
    assert trimmed[1]["tool_calls"][0]["id"] == "call_1"
    assert trimmed[2]["tool_call_id"] == "call_1"


def test_search_history_finds_message(conn):
    sid = conversation.create_session(conn, "test-model")
    conversation.add_message(conn, sid, "user", content="I love hiking in the mountains")
    conversation.add_message(conn, sid, "assistant", content="Noted!")

    results = conversation.search_history(conn, "hiking")
    assert any("hiking" in r["content"] for r in results)


def test_search_history_escapes_special_chars(conn):
    sid = conversation.create_session(conn, "test-model")
    conversation.add_message(conn, sid, "user", content="AND OR NOT are FTS5 keywords")
    # should not raise a syntax error even though query contains FTS operators
    results = conversation.search_history(conn, "AND OR NOT")
    assert isinstance(results, list)


def test_get_or_create_jobs_session_is_stable_and_separate_from_last_session(conn):
    interactive_sid = conversation.create_session(conn, "test-model")
    jobs_sid = conversation.get_or_create_jobs_session(conn, "test-model")

    assert jobs_sid != interactive_sid
    # must not have clobbered last_session_id — get_or_create_jobs_session is called
    # from a background worker process, not the interactive CLI/server session
    assert conversation.get_last_session_id(conn) == interactive_sid
    # idempotent — same session reused on subsequent calls
    assert conversation.get_or_create_jobs_session(conn, "test-model") == jobs_sid


def test_get_recent_assistant_replies(conn):
    sid = conversation.get_or_create_jobs_session(conn, "test-model")
    conversation.add_message(conn, sid, "user", content="run reflection")
    conversation.add_message(conn, sid, "assistant", content="digest 1")
    conversation.add_message(conn, sid, "assistant", content="digest 2")

    replies = conversation.get_recent_assistant_replies(conn, sid, limit=10)
    assert [r["content"] for r in replies] == ["digest 2", "digest 1"]
