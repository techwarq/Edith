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
from edith import plugins
from edith.memory import conversation
from edith.memory.brain import Brain
from edith.memory.storage import qdrant, sqlite
from edith.tools.growth import social as social_tool
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
from edith.tools.base import ToolContext
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


TOOL_MODULES = (
    notes,
    web_search,
    research_tool,
    news_tool,
    youtube_tool,
    google_gmail,
    google_drive,
    google_calendar,
    google_docs_sheets,
    whatsapp,
    health_tool,
    browse,
    tracking,
    social_tool,
    monitor_tool,
    scheduling,
    notify,
    monid_tool,
    goals_tool,
    todos_tool,
    projects_tool,
    github_tool,
    vercel_tool,
    computer_use_tool,
)


@dataclass
class AppContext:
    conn: sqlite3.Connection
    client: openai.OpenAI
    genai_client: genai.Client | None
    qdrant_client: QdrantClient | None
    agent: Agent
    registry: ToolRegistry
    settings: Settings


def build_registry(
    conn: sqlite3.Connection,
    client: openai.OpenAI,
    genai_client: genai.Client,
    model: str,
    qdrant_client: QdrantClient | None,
    settings: Settings,
) -> ToolRegistry:
    registry = ToolRegistry(
        ToolContext(
            conn=conn,
            settings=settings,
            genai_client=genai_client,
            llm_client=client,
            genai_model=model,
            qdrant_client=qdrant_client,
            brain=Brain(conn, client, qdrant_client=qdrant_client),
        )
    )
    for module in TOOL_MODULES:
        registry.register_module(module)
    for plugin in plugins.enabled():
        plugin.setup(conn)
        for module in plugin.tool_modules():
            registry.register_module(module)
    mcp_client.register_all(registry, conn)
    return registry


def resolve_session(conn: sqlite3.Connection, model: str) -> tuple[str, bool]:
    is_first_run = not conversation.any_session_exists(conn)
    last_id = conversation.get_last_session_id(conn)
    if last_id and conversation.session_exists(conn, last_id):
        return last_id, is_first_run
    return conversation.create_session(conn, model), is_first_run


def build_app_context(settings: Settings) -> AppContext:
    google_auth.write_credentials_from_env()
    conn = sqlite.connect(settings.db_path)
    client = make_client(settings.api_key)
    genai_client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None
    qdrant_client = qdrant.make_qdrant_client(settings.qdrant_url, settings.qdrant_api_key, settings.qdrant_path)
    try:
        qdrant.ensure_collection(qdrant_client)
    except Exception:
        logging.getLogger("edith.bootstrap").exception("Qdrant unreachable — starting without semantic memory")
        qdrant_client = None
    registry = build_registry(conn, client, genai_client, settings.gemini_grounding_model, qdrant_client, settings)
    agent = Agent(conn, client, settings.model, registry, registry.ctx.brain)
    registry.ctx.brain.index_pending_later()
    return AppContext(
        conn=conn,
        client=client,
        genai_client=genai_client,
        qdrant_client=qdrant_client,
        agent=agent,
        registry=registry,
        settings=settings,
    )
