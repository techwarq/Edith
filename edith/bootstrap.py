"""Shared app-context construction — used by both cli.py (terminal) and
server.py (hosted WebSocket API) so neither duplicates registry/agent setup.
"""

import sqlite3
from dataclasses import dataclass

import openai
from google import genai

from qdrant_client import QdrantClient

from edith.agent import Agent
from edith import browse
from edith.config import Settings
from edith.google import auth as google_auth
from edith.google import calendar as google_calendar
from edith.google import docs_sheets as google_docs_sheets
from edith.google import drive as google_drive
from edith.google import gmail as google_gmail
from edith.llm.client import make_client
from edith.memory import db, store, vectors
from edith.tools import goals as goals_tool
from edith.tools import health as health_tool
from edith.tools import hunter as hunter_tool
from edith.tools import mcp_client
from edith.tools import monid as monid_tool
from edith.tools import news as news_tool
from edith.tools import monitor as monitor_tool
from edith.tools import notes, notify, scheduling, tracking, web_search
from edith.tools import social as social_tool
from edith.tools import todos as todos_tool
from edith.tools import youtube as youtube_tool
from edith.tools.registry import ToolRegistry
from edith import whatsapp

WELCOME = (
    "Edith is online. I don't know anything about you yet — tell me about "
    "yourself as we go and I'll remember it.\n"
    "Commands: /afame <fact> (save a fact about you), /talk (speak instead of "
    "typing), /voice on|off (speak replies aloud), /google login (connect Gmail/"
    "Drive/Calendar/Docs/Sheets), /whatsapp login (connect WhatsApp), /health login "
    "(connect Health Connect, Android app only), /skill-talk <what you want to achieve> "
    "(tell me your niche, voice, platforms, and goals so I can give you grounded X/Instagram "
    "post and video ideas), /approve (review queued actions), "
    "/new (fresh session), /facts (what I know), /history <query> (search past "
    "conversations), /jobs [count] (recent output from scheduled jobs + nightly "
    "reflection), /exit\n"
)

EXECUTORS = {
    **google_gmail.EXECUTORS,
    **google_drive.EXECUTORS,
    **google_calendar.EXECUTORS,
    **whatsapp.EXECUTORS,
    **browse.EXECUTORS,
}


@dataclass
class AppContext:
    conn: sqlite3.Connection
    client: openai.OpenAI  # OpenRouter — the core agent's tool-calling loop, plus STT + spoken-style rewrite
    tts_client: genai.Client  # Gemini native SDK — TTS, web_search grounding, and embeddings
    qdrant_client: QdrantClient | None  # None when QDRANT_URL/QDRANT_API_KEY aren't set — semantic memory is optional
    agent: Agent
    registry: ToolRegistry
    settings: Settings


def build_registry(
    conn: sqlite3.Connection,
    genai_client: genai.Client,
    model: str,
    qdrant_client: QdrantClient | None,
    settings: Settings,
) -> ToolRegistry:
    """genai_client/model are Gemini's own (settings.gemini_grounding_model, NOT
    the core agent's settings.model) — web_search/news/youtube use Gemini's
    native Google Search grounding tool, not OpenRouter's ":online" plugin.
    genai_client doubles as the embedding client for qdrant_client-backed tools."""
    registry = ToolRegistry()
    notes.register(registry, conn, qdrant_client, genai_client)
    web_search.register(registry, genai_client, model, qdrant_client)
    news_tool.register(registry, genai_client, model)
    youtube_tool.register(registry, genai_client, model)
    google_gmail.register(registry, conn)
    google_drive.register(registry, conn)
    google_calendar.register(registry, conn)
    google_docs_sheets.register(registry, conn)
    whatsapp.register(registry, conn)
    health_tool.register(registry, conn)
    browse.register(registry, conn)
    tracking.register(registry, conn)
    social_tool.register(registry, conn, qdrant_client, genai_client)
    monitor_tool.register(registry, conn)
    scheduling.register(registry, settings)
    notify.register(registry, conn, settings)
    monid_tool.register(registry)
    goals_tool.register(registry, conn)
    todos_tool.register(registry, conn)
    hunter_tool.register(registry, settings)
    mcp_client.register_all(registry, conn)  # user-configured MCP servers — see edith/memory/mcp_store.py
    return registry


def resolve_session(conn: sqlite3.Connection, model: str) -> tuple[str, bool]:
    """Returns (session_id, is_first_run)."""
    is_first_run = not store.any_session_exists(conn)
    last_id = store.get_last_session_id(conn)
    if last_id and store.session_exists(conn, last_id):
        return last_id, is_first_run
    return store.create_session(conn, model), is_first_run


def build_app_context(settings: Settings) -> AppContext:
    google_auth.write_credentials_from_env()  # no-op locally; writes from env vars on a fresh volume
    conn = db.connect(settings.db_path)  # raises db.DatabaseError — caller decides how to report it
    client = make_client(settings.api_key)  # OpenRouter — core agent's tool-calling loop
    tts_client = genai.Client(api_key=settings.gemini_api_key)  # Gemini native SDK — TTS, web_search, embeddings
    qdrant_client = vectors.make_qdrant_client(settings.qdrant_url, settings.qdrant_api_key)
    vectors.ensure_collection(qdrant_client)
    registry = build_registry(conn, tts_client, settings.gemini_grounding_model, qdrant_client, settings)
    agent = Agent(conn, client, settings.model, registry, qdrant_client, tts_client)
    return AppContext(
        conn=conn,
        client=client,
        tts_client=tts_client,
        qdrant_client=qdrant_client,
        agent=agent,
        registry=registry,
        settings=settings,
    )
