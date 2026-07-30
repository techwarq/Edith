"""Tests for edith/server.py's _latest_job_reply (powers POST /api/jobs/latest,
the notification tap-to-open-and-speak flow). Importing edith.server builds a
real AppContext at module scope (same as running the actual server), so this
relies on real .env credentials being present, like every other manual run of
this project — there's no CI here, and no other test file imports server.py
for the same reason. store/voice calls inside it are monkeypatched so no real
API calls happen in the test itself.
"""

import edith.server as server
from edith.voice import VoiceError


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
