import pytest

import edith.server as server
from edith.integrations.voice import VoiceError


class _FakeStore:
    def __init__(self, replies):
        self.replies = replies

    def get_or_create_jobs_session(self, conn, model):
        return "fake-jobs-session"

    def get_recent_assistant_replies(self, conn, session_id, limit):
        return self.replies[:limit]


def test_latest_job_reply_empty_jobs_session(monkeypatch):
    monkeypatch.setattr(server, "store", _FakeStore([]))

    result = server._latest_job_reply()

    assert result == {"content": None, "audio_base64": None, "mime_type": None}


def test_latest_job_reply_happy_path(monkeypatch):
    monkeypatch.setattr(server, "store", _FakeStore([{"content": "Top startup news today...", "created_at": "x"}]))
    monkeypatch.setattr(server.voice, "to_spoken_style", lambda client, model, text: "Spoken: " + text)
    monkeypatch.setattr(server.voice, "synthesize", lambda client, text, model, voice: b"fake-wav-bytes")

    result = server._latest_job_reply()

    assert result["content"] == "Top startup news today..."
    assert result["mime_type"] == "audio/wav"
    import base64
    assert base64.b64decode(result["audio_base64"]) == b"fake-wav-bytes"


def test_latest_job_reply_tts_failure_falls_back_to_text_only(monkeypatch):
    monkeypatch.setattr(server, "store", _FakeStore([{"content": "Top startup news today...", "created_at": "x"}]))
    monkeypatch.setattr(server.voice, "to_spoken_style", lambda client, model, text: text)

    def fail_synthesize(*args, **kwargs):
        raise VoiceError("TTS quota exceeded")

    monkeypatch.setattr(server.voice, "synthesize", fail_synthesize)

    result = server._latest_job_reply()

    assert result == {"content": "Top startup news today...", "audio_base64": None, "mime_type": None}


@pytest.mark.parametrize(
    "text,is_stop",
    [
        ("stop", True), ("u can stop", True), ("You can stop.", True), ("ok stop now", True),
        ("Eddy, stop!", True), ("cancel that", True), ("hold on", True),
        ("stop the music", False), ("stop playing spotify and open slack", False),
        ("can you stop by the store", False), ("apply to yc", False),
    ],
)
def test_stop_intent_only_matches_pure_stop_messages(text, is_stop):
    assert bool(server._STOP_INTENT.match(text)) is is_stop
