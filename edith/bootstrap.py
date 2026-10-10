import logging
import sqlite3
from dataclasses import dataclass

import openai
from google import genai

from qdrant_client import QdrantClient

from edith.agent import Agent
from edith.integrations import browse
from edith.config import Settings
from edith.integrations.google import auth as google_auth
from edith.integrations.google import calendar as google_calendar
from edith.integrations.google import docs_sheets as google_docs_sheets
from edith.integrations.google import drive as google_drive
from edith.integrations.google import gmail as google_gmail
from edith.llm.client import make_client
from edith.memory import db, store, vectors
from edith.tools.growth import hunter as hunter_tool
from edith.tools.growth import job_applications as job_applications_tool
from edith.tools.growth import outreach as outreach_tool
from edith.tools.growth import social as social_tool
from edith.tools.growth import startup_finder as startup_finder_tool
from edith.tools.ops import github as github_tool
from edith.tools.ops import monid as monid_tool
from edith.tools.ops import monitor as monitor_tool
from edith.tools.ops import tracking
from edith.tools.ops import vercel as vercel_tool
from edith.tools.productivity import goals as goals_tool
from edith.tools.productivity import health as health_tool
from edith.tools.productivity import notes
from edith.tools.productivity import projects as projects_tool
from edith.tools.productivity import todos as todos_tool
from edith.tools.search import news as news_tool
from edith.tools.search import research as research_tool
from edith.tools.search import web_search
from edith.tools.search import youtube as youtube_tool
from edith.tools.system import computer_use as computer_use_tool
from edith.tools.system import mcp_client
from edith.tools.system import notify
from edith.tools.system import scheduling
from edith.tools.registry import ToolRegistry
from edith.integrations import whatsapp

WELCOME = (
    "Edith is online. I don't know anything about you yet — tell me about "
    "yourself as we go and I'll remember it.\n"
    "Commands: /afame <fact> (save a fact about you), /talk (speak instead of "
    "typing), /voice on|off (speak replies aloud), /google login (connect Gmail/"
    "Drive/Calendar/Docs/Sheets), /whatsapp login (connect WhatsApp), /health login "
    "(connect Health Connect, Android app only), /skill-talk <what you want to achieve> "
    "(tell me your niche, voice, platforms, and goals so I can give you grounded X/Instagram "
    "post and video ideas), /approve (review queued actions), "
    "/new (fresh session), /facts (what I know), /working-on (projects you're currently "
    "working on), /history <query> (search past conversations), /jobs [count] (recent "
    "output from scheduled jobs + nightly reflection), /exit\n"
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
    client: openai.OpenAI
    genai_client: genai.Client
    qdrant_client: QdrantClient | None
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
    registry = ToolRegistry()
    notes.register(registry, conn, qdrant_client, genai_client)
    web_search.register(registry, genai_client, model, qdrant_client)
    research_tool.register(registry, genai_client, model, qdrant_client)
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
    job_applications_tool.register(registry, conn, genai_client, model)
    outreach_tool.register(registry, conn, genai_client, model)
    startup_finder_tool.register(registry, conn, settings, genai_client, model)
    projects_tool.register(registry, conn)
    github_tool.register(registry, settings)
    vercel_tool.register(registry, settings)
    computer_use_tool.register(registry, settings)
    mcp_client.register_all(registry, conn)
    return registry


def resolve_session(conn: sqlite3.Connection, model: str) -> tuple[str, bool]:
    is_first_run = not store.any_session_exists(conn)
    last_id = store.get_last_session_id(conn)
    if last_id and store.session_exists(conn, last_id):
        return last_id, is_first_run
    return store.create_session(conn, model), is_first_run


def build_app_context(settings: Settings) -> AppContext:
    google_auth.write_credentials_from_env()
    conn = db.connect(settings.db_path)
    client = make_client(settings.api_key)
    genai_client = genai.Client(api_key=settings.gemini_api_key)
    qdrant_client = vectors.make_qdrant_client(settings.qdrant_url, settings.qdrant_api_key)
    try:
        vectors.ensure_collection(qdrant_client)
    except Exception:
        logging.getLogger("edith.bootstrap").exception("Qdrant unreachable — starting without semantic memory")
        qdrant_client = None
    registry = build_registry(conn, genai_client, settings.gemini_grounding_model, qdrant_client, settings)
    agent = Agent(conn, client, settings.model, registry, qdrant_client, genai_client)
    return AppContext(
        conn=conn,
        client=client,
        genai_client=genai_client,
        qdrant_client=qdrant_client,
        agent=agent,
        registry=registry,
        settings=settings,
    )
