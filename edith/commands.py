"""Interface-agnostic slash-command dispatch, shared by cli.py and server.py.

Every command here is a single synchronous request -> text response, with no
blocking interactive prompts — required so the same logic works identically
over a stateless WebSocket message as it does in a terminal. This is why
/approve takes an explicit action id (`/approve 3`) instead of the old CLI
loop that printed each pending action and blocked on input() for a y/n per
item: that loop can't be expressed as a single request/response.

/talk is deliberately NOT handled here — it needs a local microphone
(edith.voice.record_until_enter), which only makes sense for the CLI
interface. cli.py handles it separately, outside this dispatcher.
"""

import sqlite3

from edith.agent import Agent
from edith.bootstrap import EXECUTORS
from edith.config import Settings
from edith.google import auth as google_auth
from edith.google.auth import GoogleAuthError
from edith.memory import search as memory_search
from edith.memory import store
from edith.tools.projects import WORKING_ON_CATEGORY
from edith.integrations import whatsapp
from edith.integrations.whatsapp import WhatsAppError


def handle_command(
    command: str,
    conn: sqlite3.Connection,
    settings: Settings,
    session_id: str,
    agent: Agent,
    voice_enabled: bool,
) -> tuple[str | None, bool, str]:
    """Returns (new_session_id_or_None_to_exit, voice_enabled, output_text)."""
    parts = command.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/exit":
        return None, voice_enabled, ""

    if cmd == "/afame":
        if not arg:
            return session_id, voice_enabled, "Usage: /afame <fact about you>, e.g. /afame I work as a PM at Allore"
        directive = (
            f"Save this as a fact about me using save_fact or update_fact right now "
            f"(don't just chat about it, actually call the tool), then briefly confirm "
            f"what you saved: {arg}"
        )
        reply = agent.handle_turn(session_id, directive)
        return session_id, voice_enabled, reply

    if cmd == "/skill-talk":
        if not arg:
            return (
                session_id,
                voice_enabled,
                "Usage: /skill-talk <tell me about your content — your niche/expertise, the "
                "platforms you care about (X, Instagram), your voice/tone, and any growth or "
                "consistency goal you have>",
            )
        directive = (
            "The user is telling you what they want to achieve with their social media content, so "
            "you can act as their X/Instagram growth assistant going forward: proposing post and "
            "video ideas, and helping them stay consistent. If anything important is unclear — their "
            "niche/expertise, target platforms, voice/tone, content pillars, or a growth/posting-"
            "cadence goal — ask a brief follow-up before saving. Otherwise, save each distinct thing "
            "you learn as its own durable fact via save_fact with category='content_strategy' (don't "
            "bundle everything into one fact). If they state a concrete growth or consistency goal "
            "(e.g. 'post 3x/week', 'grow to 10k followers by December'), also call create_goal for it. "
            "If they're sharing actual reference material (a writing sample, a style guide, past post "
            "examples) rather than describing intent, use save_social_skill instead. Then briefly "
            "confirm back what you understood. Here's what they said: " + arg
        )
        reply = agent.handle_turn(session_id, directive)
        return session_id, voice_enabled, reply

    if cmd == "/voice":
        choice = arg.strip().lower()
        if choice not in ("on", "off"):
            return session_id, voice_enabled, "Usage: /voice on|off"
        voice_enabled = choice == "on"
        return session_id, voice_enabled, f"Voice replies {'enabled' if voice_enabled else 'disabled'}."

    if cmd == "/google":
        if arg.strip().lower() != "login":
            return session_id, voice_enabled, "Usage: /google login"
        try:
            google_auth.run_login_flow()
            return session_id, voice_enabled, "Google account connected."
        except GoogleAuthError as e:
            return session_id, voice_enabled, f"Error: {e}"

    if cmd == "/whatsapp":
        if arg.strip().lower() != "login":
            return session_id, voice_enabled, "Usage: /whatsapp login"
        try:
            whatsapp.login()
            return session_id, voice_enabled, "WhatsApp connected."
        except WhatsAppError as e:
            return session_id, voice_enabled, f"Error: {e}"

    if cmd in ("/approve", "/reject"):
        target_status = "approved" if cmd == "/approve" else "rejected"

        if not arg.strip():
            pending = store.get_pending_actions(conn, status="pending")
            if not pending:
                return session_id, voice_enabled, "No pending actions."
            lines = [f"#{a['id']} ({a['tool_name']}): {a['preview']}" for a in pending]
            lines.append("Reply /approve <id> to confirm, or /reject <id> to decline.")
            return session_id, voice_enabled, "\n\n".join(lines)

        try:
            action_id = int(arg.strip())
        except ValueError:
            return session_id, voice_enabled, f"Usage: {cmd} <id> (a number from the pending list)"

        resolved = store.resolve_pending_action(conn, action_id, target_status)
        if resolved is None:
            return session_id, voice_enabled, f"No pending action with id {action_id}."
        if target_status == "rejected":
            return session_id, voice_enabled, f"Rejected action #{action_id}."

        executor = EXECUTORS.get(resolved["tool_name"])
        if executor is None:
            return session_id, voice_enabled, f"ERROR: no executor registered for '{resolved['tool_name']}'."
        google_creds = google_auth.get_credentials()  # nullable; each executor guards its own precondition
        result = executor(google_creds, resolved["args"])
        return session_id, voice_enabled, result

    if cmd == "/new":
        store.end_session(conn, session_id)
        new_id = store.create_session(conn, settings.model)
        return new_id, voice_enabled, f"Started a new session ({new_id[:8]})."

    if cmd == "/facts":
        facts = store.get_all_facts(conn)
        if not facts:
            return session_id, voice_enabled, "No facts stored yet."
        lines = [f"[{f['category']}] {f['key']}: {f['value']}" if f["category"] else f"{f['key']}: {f['value']}" for f in facts]
        return session_id, voice_enabled, "\n".join(lines)

    if cmd == "/working-on":
        facts = store.get_facts_by_category(conn, WORKING_ON_CATEGORY)
        if not facts:
            return session_id, voice_enabled, "Nothing tracked yet — tell me what you're working on and I'll remember it."
        lines = [f"{f['key']}: {f['value']}" for f in facts]
        return session_id, voice_enabled, "\n".join(lines)

    if cmd == "/jobs":
        limit = 10
        if arg.strip():
            try:
                limit = int(arg.strip())
            except ValueError:
                return session_id, voice_enabled, "Usage: /jobs [count]"
        jobs_session_id = store.get_or_create_jobs_session(conn, settings.model)
        replies = store.get_recent_assistant_replies(conn, jobs_session_id, limit)
        if not replies:
            return session_id, voice_enabled, "No scheduled job output yet."
        lines = [f"--- [{r['created_at']}] ---\n{r['content']}" for r in replies]
        return session_id, voice_enabled, "\n\n".join(lines)

    if cmd == "/history":
        if not arg:
            return session_id, voice_enabled, "Usage: /history <query>"
        results = memory_search.search_history(conn, arg)
        if not results:
            return session_id, voice_enabled, "No matching past messages found."
        lines = [f"[{r['created_at']}] {r['role']}: {r['content']}" for r in results]
        return session_id, voice_enabled, "\n".join(lines)

    return session_id, voice_enabled, f"Unknown command: {cmd}"
