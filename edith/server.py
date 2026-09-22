"""Hosted API — the network equivalent of cli.py's terminal REPL.

Each turn (a typed message or a recorded voice clip) is one POST request
that gets back a text/event-stream response: the server does its work
(agent reply, optional transcription, optional TTS) and streams a few SSE
events before closing. There is no persistent connection between turns —
deliberately simpler than the previous /ws WebSocket design, which needed a
keepalive ping loop to stop Railway's proxy from dropping an idle connection
and was still closing early. Since nothing here needs real-time duplex
voice-to-voice (mic input is a full clip, not a live stream), a short-lived
per-request connection has nothing to time out.

agent.handle_turn() and handle_command() are synchronous, blocking calls
(they make real HTTP requests to OpenRouter/Google/etc.) — run via
asyncio.to_thread() so a slow LLM call doesn't block the event loop.
voice.transcribe()/synthesize() are the same kind of blocking call and get
the same treatment.
"""

import asyncio
import base64
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from edith import voice
from edith.bootstrap import build_app_context, resolve_session
from edith.commands import handle_command
from edith.config import WHATSAPP_QR_PATH, load_settings
from edith.memory import db, store
from edith.goals import api as goals_api
from edith.job_applications import api as job_applications_api
from edith.mcp import api as mcp_api
from edith.memory import health as health_metrics
from edith.monitor import api as monitor_api
from edith.observability import api as observability_api
from edith.observability.seed_evals import seed_default_evals
from edith.temporal import api as deep_research_api
from edith.todos import api as todos_api
from edith.voice import VoiceError
from edith.linkedin import api as linkedin_api
from edith.computer_use.typesafe_client import TypeSafeClient, TypeSafeError
from edith.computer_use.voice_loop import SITES, VoiceTickSession
from edith.computer_use.writer import make_writer_client

logger = logging.getLogger("edith.server")

settings = load_settings()
try:
    ctx = build_app_context(settings)
except db.DatabaseError as e:
    raise SystemExit(f"Error: {e}") from e

API_TOKEN = os.environ.get("EDITH_API_TOKEN", "").strip()
WEB_DIR = Path(__file__).parent / "web"

seed_default_evals(ctx.conn)

app = FastAPI()
app.include_router(
    observability_api.build_router(ctx.conn, ctx.agent, ctx.client, settings.openrouter_text_model, API_TOKEN)
)
app.include_router(goals_api.build_router(ctx.conn, API_TOKEN))
app.include_router(todos_api.build_router(ctx.conn, API_TOKEN))
app.include_router(mcp_api.build_router(ctx.conn, API_TOKEN))
app.include_router(deep_research_api.build_router(ctx.conn, settings, API_TOKEN))
app.include_router(monitor_api.build_router(ctx.conn, settings, ctx.genai_client, API_TOKEN))
app.include_router(job_applications_api.build_router(ctx.conn, API_TOKEN))
app.include_router(linkedin_api.build_router(ctx.conn, ctx.genai_client, API_TOKEN))


@app.middleware("http")
async def no_cache_web_assets(request: Request, call_next):
    """The Android app (Capacitor) and browsers otherwise cache index.html/app.js
    across restarts, so a deploy that changes the frontend's transport (e.g. the
    WebSocket -> SSE switch) can silently keep running the stale cached JS against
    a server that no longer has the old routes. Force revalidation on every load."""
    response = await call_next(request)
    if request.url.path in ("/", "/index.html", "/app.js"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/whatsapp-qr", response_model=None)
async def whatsapp_qr(token: str = "") -> FileResponse | JSONResponse:
    # Token-protected: this serves a live WhatsApp Web login QR code — anyone who
    # scans it before you do could link a device to your account.
    if not API_TOKEN or token != API_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not WHATSAPP_QR_PATH.exists():
        return JSONResponse(
            {"error": "No QR code available yet — send /whatsapp login in the chat first."}, status_code=404
        )
    # no-store: the QR expires in ~20-30s and a fresh /whatsapp login overwrites this same
    # file, so a cached browser response could silently keep showing an old, dead QR code.
    return FileResponse(str(WHATSAPP_QR_PATH), media_type="image/png", headers={"Cache-Control": "no-store"})


def _unauthorized(body: dict) -> JSONResponse | None:
    if not API_TOKEN or body.get("token") != API_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


@app.post("/api/connect", response_model=None)
async def connect(request: Request) -> JSONResponse:
    body = await request.json()
    if (err := _unauthorized(body)) is not None:
        return err
    session_id, _ = await asyncio.to_thread(resolve_session, ctx.conn, settings.model)
    return JSONResponse({"session_id": session_id})


def _store_health_metrics(metrics: list[dict]) -> int:
    """Runs on a worker thread (see the endpoint below) — plain sync SQLite
    calls, same pattern as every other blocking call in this file."""
    written = health_metrics.store_metrics(ctx.conn, metrics)
    latest_weight = next((m for m in reversed(metrics) if m.get("type") == "weight"), None)
    if latest_weight:
        # Keeps the latest weight visible in the system prompt's profile block
        # without Edith needing to call a tool for basic "what's my weight" context —
        # same pattern used for every other durable fact (see edith/tools/notes.py).
        store.save_fact(
            ctx.conn,
            key="current_weight",
            value=f"{latest_weight['value']} {latest_weight.get('unit') or 'kg'} (as of {latest_weight['date']})",
            category="fact",
        )
    return written


@app.post("/api/health-data", response_model=None)
async def health_data(request: Request) -> JSONResponse:
    body = await request.json()
    if (err := _unauthorized(body)) is not None:
        return err
    metrics = body.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        return JSONResponse({"error": "metrics must be a non-empty list"}, status_code=400)
    written = await asyncio.to_thread(_store_health_metrics, metrics)
    return JSONResponse({"written": written})


@app.post("/api/register_device", response_model=None)
async def register_device(request: Request) -> JSONResponse:
    body = await request.json()
    if (err := _unauthorized(body)) is not None:
        return err
    device_token = body.get("device_token", "").strip()
    platform = body.get("platform", "android").strip() or "android"
    if not device_token:
        return JSONResponse({"error": "device_token is required"}, status_code=400)
    await asyncio.to_thread(store.save_device_token, ctx.conn, device_token, platform)
    return JSONResponse({"ok": True})


def _latest_job_reply() -> dict:
    """Runs on a worker thread (see the endpoint below) — same blocking-call
    pattern as every other sync helper in this file. Powers the notification
    tap-to-open-and-speak flow: fetches the most recent scheduled-job output
    and synthesizes it, reusing the exact same voice pipeline _handle_turn's
    voice_enabled branch already uses for normal chat replies."""
    session_id = store.get_or_create_jobs_session(ctx.conn, settings.model)
    replies = store.get_recent_assistant_replies(ctx.conn, session_id, 1)
    if not replies:
        return {"content": None, "audio_base64": None, "mime_type": None}

    content = replies[0]["content"]
    try:
        spoken_text = voice.to_spoken_style(ctx.client, settings.openrouter_text_model, content)
        audio_bytes = voice.synthesize(ctx.client, spoken_text, settings.tts_model, settings.tts_voice)
        return {
            "content": content,
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "mime_type": "audio/wav",
        }
    except VoiceError:
        logger.exception("TTS failed for /api/jobs/latest — returning text only")
        return {"content": content, "audio_base64": None, "mime_type": None}


@app.post("/api/jobs/latest", response_model=None)
async def jobs_latest(request: Request) -> JSONResponse:
    body = await request.json()
    if (err := _unauthorized(body)) is not None:
        return err
    result = await asyncio.to_thread(_latest_job_reply)
    return JSONResponse(result)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# X-Accel-Buffering: no stops nginx-style proxies (Railway's edge included) from
# buffering the whole response before forwarding it — without it, heartbeats
# below wouldn't reach the client until the stream closed, defeating the point.
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


SSE_HEARTBEAT_SECONDS = 15  # some slash commands (e.g. /whatsapp login) block for
# minutes waiting on something external (a QR scan). A plain SSE comment line
# every few seconds keeps bytes flowing so Railway's proxy doesn't treat the
# connection as idle and kill it before the blocking call finishes.


async def _heartbeat_until_done(task: "asyncio.Task") -> AsyncIterator[str]:
    """Yields SSE comment-line heartbeats while task is in flight. Comment
    lines (":...") are ignored by SSE clients — they exist only to keep bytes
    flowing. Caller reads the real result via task.result() once this returns."""
    while not task.done():
        done, _ = await asyncio.wait({task}, timeout=SSE_HEARTBEAT_SECONDS)
        if not done:
            yield ": keepalive\n\n"


class _ProgressRunner:
    """Runs func(*args, on_progress=...) in a thread and surfaces live "what is
    Edith doing" status as real SSE "status" events (e.g. "Searching the web")
    instead of silent keepalives — on_progress pushes status strings onto a
    queue from the worker thread; .events() drains that queue and forwards
    each one to the client as soon as it arrives, falling back to a plain
    heartbeat when nothing's been reported in a while. The task is exposed as
    an attribute so the caller can read the real return value via
    self.task.result() once .events() is exhausted (an async generator can't
    itself return a value)."""

    def __init__(self, func, *args) -> None:
        loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue = asyncio.Queue()

        def on_progress(status: str) -> None:
            loop.call_soon_threadsafe(self._queue.put_nowait, status)

        self.task = asyncio.create_task(asyncio.to_thread(func, *args, on_progress=on_progress))

    async def events(self) -> AsyncIterator[str]:
        while not self.task.done():
            get_task = asyncio.create_task(self._queue.get())
            done, _ = await asyncio.wait(
                {self.task, get_task}, timeout=SSE_HEARTBEAT_SECONDS, return_when=asyncio.FIRST_COMPLETED
            )
            if get_task in done:
                yield _sse("status", {"content": get_task.result()})
            else:
                get_task.cancel()
                try:
                    await get_task
                except asyncio.CancelledError:
                    pass
                if self.task not in done:
                    yield ": keepalive\n\n"
        while not self._queue.empty():
            yield _sse("status", {"content": self._queue.get_nowait()})


@app.post("/api/message", response_model=None)
async def message(request: Request) -> StreamingResponse | JSONResponse:
    body = await request.json()
    if (err := _unauthorized(body)) is not None:
        return err
    session_id = body.get("session_id", "")
    text = body.get("text", "").strip()
    voice_enabled = bool(body.get("voice_enabled", False))
    if not session_id or not text:
        return JSONResponse({"error": "session_id and text are required"}, status_code=400)

    return StreamingResponse(_handle_turn(session_id, text, voice_enabled), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/api/audio", response_model=None)
async def audio(request: Request) -> StreamingResponse | JSONResponse:
    body = await request.json()
    if (err := _unauthorized(body)) is not None:
        return err
    session_id = body.get("session_id", "")
    data = body.get("data", "")
    mime_type = body.get("mime_type", "audio/webm")
    if not session_id or not data:
        return JSONResponse({"error": "session_id and data are required"}, status_code=400)

    return StreamingResponse(_handle_audio(session_id, data, mime_type), media_type="text/event-stream", headers=_SSE_HEADERS)



# Per-session VoiceTickSession, keyed by the same session_id /api/connect
# hands out — holds a live pinned-window AXUIElement across ticks, which
# can't be persisted to the DB like the rest of session state (store.py)
# anyway, so an in-memory dict is the natural fit here, same tier as
# runner.py's own local-machine-only design.
_voice_tick_sessions: dict[str, VoiceTickSession] = {}


def _get_voice_tick_session(session_id: str) -> VoiceTickSession:
    session = _voice_tick_sessions.get(session_id)
    if session is None:
        client = TypeSafeClient(settings.api_key)
        writer_client = make_writer_client(settings.api_key) if settings.api_key else None
        session = VoiceTickSession(
            client,
            sites=SITES,
            writer_client=writer_client,
            writer_model=settings.computer_use_writer_model,
            confidence_threshold=settings.computer_use_confidence_threshold,
        )
        _voice_tick_sessions[session_id] = session
    return session


@app.post("/api/voice_tick", response_model=None)
async def voice_tick(request: Request) -> JSONResponse:
    """One tick of the fixed-questions/live-state voice loop (see
    edith/computer_use/voice_loop.py) — a fast single round trip, not an
    agent turn, so plain JSON rather than SSE. Called repeatedly (debounced
    client-side to ~180-200ms) with the growing transcript for one
    continuous Control-hold session."""
    body = await request.json()
    if (err := _unauthorized(body)) is not None:
        return err
    session_id = body.get("session_id", "")
    transcript = body.get("transcript", "")
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=400)
    try:
        session = _get_voice_tick_session(session_id)
        result = await asyncio.to_thread(session.tick, transcript)
    except TypeSafeError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return JSONResponse(result.to_dict())


@app.post("/api/voice_tick_end", response_model=None)
async def voice_tick_end(request: Request) -> JSONResponse:
    """Called when Control is released — discards the session's pinned
    window/history so the next hold starts clean rather than continuing to
    act on whatever window the previous hold left pinned."""
    body = await request.json()
    if (err := _unauthorized(body)) is not None:
        return err
    session_id = body.get("session_id", "")
    _voice_tick_sessions.pop(session_id, None)
    return JSONResponse({"ok": True})


async def _handle_audio(session_id: str, data: str, mime_type: str) -> AsyncIterator[str]:
    try:
        audio_bytes = base64.b64decode(data)
        ext = mime_type.split("/")[-1].split(";")[0]
        import pathlib, time  # noqa: PLC0415 — temporary debug capture, remove after diagnosis
        pathlib.Path(f"/tmp/edith-debug-audio-{int(time.time())}.{ext}").write_bytes(audio_bytes)
        text = await asyncio.to_thread(
            voice.transcribe, ctx.client, audio_bytes, settings.stt_model, f"recording.{ext}", mime_type
        )
    except VoiceError as e:
        yield _sse("text", {"content": f"(voice error: {e})"})
        return
    except Exception:  # noqa: BLE001
        logger.exception("Failed to decode/transcribe incoming audio")
        yield _sse("text", {"content": "(voice error: could not process audio)"})
        return

    yield _sse("transcript", {"content": text})
    if not text.strip():
        return

    async for event in _handle_turn(session_id, text, voice_enabled=True):
        yield event


async def _handle_turn(session_id: str, text: str, voice_enabled: bool) -> AsyncIterator[str]:
    if text.startswith("/"):
        task = asyncio.create_task(
            asyncio.to_thread(handle_command, text, ctx.conn, settings, session_id, ctx.agent, voice_enabled)
        )
        async for heartbeat in _heartbeat_until_done(task):
            yield heartbeat
        new_session_id, new_voice_enabled, output = task.result()

        if new_session_id is None:
            yield _sse("text", {"content": "Goodbye."})
            return
        if output:
            yield _sse("text", {"content": output})
        if new_session_id != session_id:
            yield _sse("session", {"session_id": new_session_id})
        yield _sse("voice_enabled", {"voice_enabled": new_voice_enabled})
        return

    runner = _ProgressRunner(ctx.agent.handle_turn, session_id, text)
    async for event in runner.events():
        yield event
    reply = runner.task.result()
    yield _sse("text", {"content": reply})

    if voice_enabled:
        try:
            spoken_text = await asyncio.to_thread(
                voice.to_spoken_style, ctx.client, settings.openrouter_text_model, reply
            )
            audio_bytes = await asyncio.to_thread(
                voice.synthesize, ctx.client, spoken_text, settings.tts_model, settings.tts_voice
            )
            yield _sse("audio", {"data": base64.b64encode(audio_bytes).decode("ascii"), "mime_type": "audio/wav"})
        except VoiceError as e:
            yield _sse("text", {"content": f"(voice warning: {e})"})


class _NoCacheStaticFiles(StaticFiles):
    """Plain StaticFiles sends no explicit Cache-Control header, so browsers
    (and Electron's Chromium) apply heuristic caching off Last-Modified —
    which can serve a stale index.html/app.js/dashboard.js even across a
    reload, well after a new version has been deployed (this happened for
    real on 2026-07-29: the server had the fixed CSS, the client didn't).
    no-store forces a full refetch every load — fine for a personal app's
    handful of small JS/CSS files."""

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


if WEB_DIR.exists():
    app.mount("/", _NoCacheStaticFiles(directory=str(WEB_DIR), html=True), name="web")
