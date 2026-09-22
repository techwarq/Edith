"""Audio I/O: mic recording, speech-to-text, and text-to-speech playback.

This is the interface layer, not the core — unlike agent.py/llm/memory/tools,
this module is explicitly allowed to do real I/O (mic capture, subprocess
playback). Every function here raises VoiceError on failure so callers
(cli.py) can catch one exception type and print a friendly warning instead
of crashing the REPL over a mic glitch or a TTS hiccup.
"""

import io
import logging
import subprocess
import tempfile
import wave
from pathlib import Path

import openai

from edith.config import MAX_RECORD_SECONDS

logger = logging.getLogger("edith.voice")

SAMPLE_RATE = 16000
CHANNELS = 1
SPOKEN_STYLE_MAX_TOKENS = 512
TTS_SAMPLE_RATE = 24000  # kokoro-82m's native output rate

SPOKEN_STYLE_PROMPT = (
    "Rewrite the following so it sounds natural when read aloud by a warm, friendly "
    "voice assistant — not a document being recited, but also not overly hyped up or "
    "gushing. Keep the friendliness understated, not try-hard. "
    "Rules: no markdown (no **bold**, no bullet points, no numbered lists, no headers, "
    "no emojis); no exclamation points; avoid hype words like 'great', 'awesome', "
    "'exciting'; turn lists into flowing conversational sentences ('first... then... "
    "and finally...' or similar); do NOT add any facts, details, context, or commentary "
    "that isn't already in the original text — only rephrase what's there; do NOT pad "
    "it out or make it longer than the original — say it as briefly as the original "
    "allows, never longer. "
    "Return only the rewritten text, nothing else — no preamble, no quotes around it."
)


class VoiceError(Exception):
    pass


def record_until_enter(samplerate: int = SAMPLE_RATE) -> bytes:
    """Records mic audio in a background stream until Enter is pressed
    (or MAX_RECORD_SECONDS elapses as a safety cap). Returns WAV bytes.

    numpy/sounddevice are imported here, not at module scope, so importing
    edith.voice doesn't require PortAudio (a system library) to be installed —
    the hosted server never calls this (mic capture happens in the browser),
    and its Docker image doesn't have PortAudio."""
    import numpy as np
    import sounddevice as sd

    frames: list[np.ndarray] = []

    def callback(indata, frame_count, time_info, status):  # noqa: ARG001
        if status:
            logger.warning("sounddevice status: %s", status)
        frames.append(indata.copy())

    try:
        with sd.InputStream(
            samplerate=samplerate, channels=CHANNELS, dtype="int16", callback=callback
        ):
            try:
                input()  # blocks until Enter; recording continues via the callback thread
            except EOFError:
                pass
    except sd.PortAudioError as e:
        raise VoiceError(f"Could not access the microphone: {e}") from e

    if not frames:
        raise VoiceError("No audio was captured.")

    audio = np.concatenate(frames, axis=0)
    max_samples = MAX_RECORD_SECONDS * samplerate
    if len(audio) > max_samples:
        audio = audio[:max_samples]

    return _pcm_to_wav_bytes(audio.tobytes(), samplerate, CHANNELS)


def _pcm_to_wav_bytes(pcm_bytes: bytes, samplerate: int, channels: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # int16
        wf.setframerate(samplerate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def transcribe(
    client: openai.OpenAI,
    audio_bytes: bytes,
    model: str,
    filename: str = "recording.wav",
    content_type: str = "audio/wav",
) -> str:
    """filename/content_type are overridable because the CLI records WAV
    (via sounddevice) but a browser's MediaRecorder produces webm/opus by
    default — the transcription API needs the real container format."""
    try:
        result = client.audio.transcriptions.create(
            model=model,
            file=(filename, audio_bytes, content_type),
        )
        text = getattr(result, "text", None)
        if not text:
            raise VoiceError("Transcription returned no text.")
        return text
    except VoiceError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("Transcription failed")
        raise VoiceError(f"Transcription failed: {e}") from e


def to_spoken_style(client: openai.OpenAI, chat_model: str, text: str) -> str:
    """Rewrites a (possibly markdown-formatted, list-heavy) chat reply into
    natural spoken phrasing before it's handed to speak(). Falls back to the
    original text on any failure — better to speak something than nothing."""
    try:
        resp = client.chat.completions.create(
            model=chat_model,
            messages=[
                {"role": "system", "content": SPOKEN_STYLE_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=SPOKEN_STYLE_MAX_TOKENS,
        )
        rewritten = resp.choices[0].message.content
        return rewritten.strip() if rewritten else text
    except Exception:  # noqa: BLE001
        logger.exception("to_spoken_style failed, falling back to original text")
        return text


def synthesize(client: openai.OpenAI, text: str, model: str, voice: str) -> bytes:
    """TTS only — returns WAV bytes, no playback. Used by server.py (the
    client's browser plays the audio, not this machine) and by speak() below.

    Uses OpenRouter's OpenAI-compatible /api/v1/audio/speech endpoint (same
    `client` as the core agent's tool-calling loop and transcribe()'s STT
    call) — hexgrad/kokoro-82m as of 2026-07-31. OpenRouter's endpoint only
    accepts response_format "mp3" or "pcm" (requesting "wav" 400s with a
    ZodError) so raw PCM is requested and hand-wrapped into a WAV header,
    same as the Gemini native-TTS path this replaced."""
    try:
        resp = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="pcm",
        )
        return _pcm_to_wav_bytes(resp.content, TTS_SAMPLE_RATE, CHANNELS)
    except Exception as e:  # noqa: BLE001
        logger.exception("TTS synthesis failed")
        raise VoiceError(f"Text-to-speech failed: {e}") from e


def play_locally(audio_bytes: bytes) -> None:
    """Plays WAV bytes through this machine's speakers via afplay. CLI-only —
    a hosted server has no speakers; the client (browser/APK) plays audio itself."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = Path(f.name)
    try:
        tmp_path.write_bytes(audio_bytes)
        subprocess.run(["afplay", str(tmp_path)], check=True)
    except subprocess.CalledProcessError as e:
        raise VoiceError(f"Audio playback failed: {e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)


def speak(client: openai.OpenAI, text: str, model: str, voice: str) -> None:
    """CLI convenience wrapper: synthesize + play through local speakers."""
    audio_bytes = synthesize(client, text, model, voice)
    play_locally(audio_bytes)
