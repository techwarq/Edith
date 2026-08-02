"""Terminal REPL — the only place in this module doing I/O (print/input).

Slash commands other than /talk are dispatched through edith.commands
(shared with server.py). /talk stays here because it needs a local
microphone (edith.voice.record_until_enter), which only makes sense for
the terminal interface.
"""

import logging
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from edith import voice
from edith.bootstrap import WELCOME, build_app_context, resolve_session
from edith.commands import handle_command
from edith.config import Settings, load_settings
from edith.memory import db, store
from edith.voice import VoiceError


def _setup_logging(log_path) -> None:
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _speak_safely(client, text: str, settings: Settings) -> None:
    """client is OpenRouter (ctx.client) — used for both the spoken-style
    rewrite and TTS synthesis."""
    try:
        spoken_text = voice.to_spoken_style(client, settings.openrouter_text_model, text)
        voice.speak(client, spoken_text, settings.tts_model, settings.tts_voice)
    except VoiceError as e:
        print(f"(voice warning: {e})")


def main() -> None:
    settings = load_settings()
    _setup_logging(settings.log_path)

    try:
        ctx = build_app_context(settings)
    except db.DatabaseError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    conn, client, agent = ctx.conn, ctx.client, ctx.agent
    session_id, is_first_run = resolve_session(conn, settings.model)
    voice_enabled = False

    if is_first_run:
        print(WELCOME)
    else:
        print(f"Edith is online. Resuming session {session_id[:8]}. (/new for a fresh one, /exit to quit)")

    prompt_session: PromptSession = PromptSession(history=FileHistory(str(settings.history_path)))

    while True:
        try:
            user_text = prompt_session.prompt("edith> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not user_text:
            continue

        if user_text.startswith("/talk"):
            print("Recording... press Enter to stop.")
            try:
                wav_bytes = voice.record_until_enter()
                transcript = voice.transcribe(client, wav_bytes, settings.stt_model)
            except VoiceError as e:
                print(f"Voice error: {e}")
                continue
            print(f"You (voice): {transcript}")
            reply = agent.handle_turn(session_id, transcript)
            print(f"Edith: {reply}")
            _speak_safely(client, reply, settings)  # always speak /talk replies
            continue

        if user_text.startswith("/"):
            session_id, voice_enabled, output = handle_command(
                user_text, conn, settings, session_id, agent, voice_enabled
            )
            if session_id is None:
                break
            if output:
                print(output)
                if voice_enabled:
                    _speak_safely(client, output, settings)
            continue

        reply = agent.handle_turn(session_id, user_text)
        print(f"Edith: {reply}")
        if voice_enabled:
            _speak_safely(client, reply, settings)

    store.end_session(conn, session_id)
    conn.close()


if __name__ == "__main__":
    main()
