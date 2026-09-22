import io
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from edith.integrations import voice
from edith.integrations.voice import VoiceError


# ---------------------------------------------------------------------------
# WAV packaging
# ---------------------------------------------------------------------------

def test_pcm_to_wav_bytes_roundtrip():
    pcm = b"\x00\x01" * 8000
    wav_bytes = voice._pcm_to_wav_bytes(pcm, 16000, 1)
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000
        assert wf.getsampwidth() == 2
        assert wf.getnframes() == 8000


# ---------------------------------------------------------------------------
# record_until_enter (mic input mocked — no real hardware in tests)
# ---------------------------------------------------------------------------

class FakeInputStream:
    def __init__(self, samplerate, channels, dtype, callback):
        self.callback = callback

    def __enter__(self):
        self.callback(np.zeros((100, 1), dtype="int16"), 100, None, None)
        return self

    def __exit__(self, *args):
        return False


class EmptyInputStream(FakeInputStream):
    def __enter__(self):
        return self  # never invokes the callback — simulates zero captured audio


def test_record_until_enter_returns_wav_bytes(monkeypatch):
    # sounddevice/numpy are imported lazily inside record_until_enter() (so importing
    # edith.voice doesn't require PortAudio on the server) — patch the real
    # sounddevice module directly rather than a module-level voice.sd that no longer exists.
    monkeypatch.setattr("sounddevice.InputStream", FakeInputStream)
    monkeypatch.setattr("builtins.input", lambda: "")
    wav_bytes = voice.record_until_enter(samplerate=16000)
    assert wav_bytes[:4] == b"RIFF"


def test_record_until_enter_no_audio_raises(monkeypatch):
    monkeypatch.setattr("sounddevice.InputStream", EmptyInputStream)
    monkeypatch.setattr("builtins.input", lambda: "")
    with pytest.raises(VoiceError):
        voice.record_until_enter()


# ---------------------------------------------------------------------------
# transcribe
# ---------------------------------------------------------------------------

class FakeTranscriptionResult:
    def __init__(self, text):
        self.text = text


class FakeTranscriptions:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.result


class FakeAudio:
    def __init__(self, transcriptions=None, speech=None):
        self.transcriptions = transcriptions
        self.speech = speech


class FakeClient:
    def __init__(self, audio=None, chat=None):
        self.audio = audio
        self.chat = chat


def test_transcribe_success():
    transcriptions = FakeTranscriptions(result=FakeTranscriptionResult("hello world"))
    client = FakeClient(FakeAudio(transcriptions=transcriptions))
    text = voice.transcribe(client, b"fakewav", "test-stt-model")
    assert text == "hello world"
    assert transcriptions.calls[0]["model"] == "test-stt-model"


def test_transcribe_empty_text_raises():
    transcriptions = FakeTranscriptions(result=FakeTranscriptionResult(""))
    client = FakeClient(FakeAudio(transcriptions=transcriptions))
    with pytest.raises(VoiceError):
        voice.transcribe(client, b"fakewav", "test-stt-model")


def test_transcribe_api_error_wrapped():
    transcriptions = FakeTranscriptions(exc=RuntimeError("boom"))
    client = FakeClient(FakeAudio(transcriptions=transcriptions))
    with pytest.raises(VoiceError):
        voice.transcribe(client, b"fakewav", "test-stt-model")


# ---------------------------------------------------------------------------
# speak (OpenRouter TTS via client.audio.speech.create, hexgrad/kokoro-82m)
# ---------------------------------------------------------------------------

class FakeSpeechResponse:
    def __init__(self, content: bytes):
        self.content = content


class FakeSpeech:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.response


def _fake_wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x01" * 100)
    return buf.getvalue()


def test_synthesize_returns_wav_bytes():
    speech = FakeSpeech(response=FakeSpeechResponse(_fake_wav_bytes()))
    client = FakeClient(FakeAudio(speech=speech))

    audio_bytes = voice.synthesize(client, "hello", "test-tts-model", "af_heart")

    assert audio_bytes[:4] == b"RIFF"
    assert speech.calls[0]["model"] == "test-tts-model"
    assert speech.calls[0]["voice"] == "af_heart"
    assert speech.calls[0]["input"] == "hello"
    assert speech.calls[0]["response_format"] == "pcm"


def test_synthesize_failure_raises():
    speech = FakeSpeech(exc=RuntimeError("boom"))
    client = FakeClient(FakeAudio(speech=speech))
    with pytest.raises(VoiceError):
        voice.synthesize(client, "hello", "test-tts-model", "af_heart")


def test_play_locally_success(monkeypatch):
    playback_calls = []
    written_paths = []

    def fake_run(args, check):
        written_paths.append(Path(args[1]))
        playback_calls.append(args)

    monkeypatch.setattr(voice.subprocess, "run", fake_run)

    voice.play_locally(b"fake-wav-bytes")

    assert playback_calls[0][0] == "afplay"
    assert not written_paths[0].exists()  # temp file cleaned up


def test_play_locally_failure_raises(monkeypatch):
    def fail_run(args, check):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(voice.subprocess, "run", fail_run)

    with pytest.raises(VoiceError):
        voice.play_locally(b"fake-wav-bytes")


def test_speak_synthesizes_and_plays(monkeypatch):
    playback_calls = []
    monkeypatch.setattr(voice.subprocess, "run", lambda args, check: playback_calls.append(args))
    speech = FakeSpeech(response=FakeSpeechResponse(_fake_wav_bytes()))
    client = FakeClient(FakeAudio(speech=speech))

    voice.speak(client, "hello", "test-tts-model", "af_heart")

    assert speech.calls[0]["model"] == "test-tts-model"
    assert playback_calls[0][0] == "afplay"


# ---------------------------------------------------------------------------
# to_spoken_style
# ---------------------------------------------------------------------------

class FakeChatMessage:
    def __init__(self, content):
        self.content = content


class FakeChatChoice:
    def __init__(self, content):
        self.message = FakeChatMessage(content)


class FakeChatResponse:
    def __init__(self, content):
        self.choices = [FakeChatChoice(content)]


class FakeChatCompletions:
    def __init__(self, content=None, exc=None):
        self.content = content
        self.exc = exc
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return FakeChatResponse(self.content)


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


def test_to_spoken_style_rewrites_text():
    completions = FakeChatCompletions(content="First, your mom messaged you. Then Abhisek shared a photo.")
    client = FakeClient(chat=FakeChat(completions))

    result = voice.to_spoken_style(client, "test-model", "1. **Mom**: hi\n2. **Abhisek**: 📷 Photo")

    assert result == "First, your mom messaged you. Then Abhisek shared a photo."
    assert completions.calls[0]["model"] == "test-model"
    assert completions.calls[0]["messages"][1]["content"] == "1. **Mom**: hi\n2. **Abhisek**: 📷 Photo"


def test_to_spoken_style_falls_back_to_original_on_error():
    completions = FakeChatCompletions(exc=RuntimeError("boom"))
    client = FakeClient(chat=FakeChat(completions))

    original = "**Bold** list:\n- one\n- two"
    result = voice.to_spoken_style(client, "test-model", original)

    assert result == original
