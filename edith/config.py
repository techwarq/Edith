"""Environment-based settings, ~/.edith/* paths, startup validation."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

EDITH_HOME = Path(os.environ.get("EDITH_HOME", Path.home() / ".edith"))
DB_PATH = Path(os.environ.get("EDITH_DB_PATH", EDITH_HOME / "edith.db"))
LOG_PATH = EDITH_HOME / "edith.log"
HISTORY_PATH = EDITH_HOME / "repl_history"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# Core agent's chat/tool-calling model, via OpenRouter. Was gemini-3.5-flash
# (Gemini's own OpenAI-compat endpoint) from 2026-07-18, swapped back to Qwen
# on 2026-07-28: Gemini 3.5 Flash's internal "thinking" tokens share the same
# max_tokens budget as the visible answer, and on synthesis-heavy turns it
# repeatedly spent the whole budget reasoning and never emitted any visible
# text — msg.content came back None with completion_tokens ~1900-2000, i.e. a
# blank reply despite an apparently successful "ok" turn (traces
# 24a7dc74/af4136bf). Qwen has no such thinking-token/content split.
DEFAULT_MODEL = "qwen/qwen3.7-flash"
# Small OpenRouter model kept only for the voice pipeline's spoken-style rewrite
# step (web_search moved to Gemini's own native Google Search grounding on
# 2026-07-19, so it no longer needs this). Not user-facing — quiet plumbing.
DEFAULT_OPENROUTER_TEXT_MODEL = "qwen/qwen3-coder-next"
# Gemini model used only for web_search/news/youtube's native Google Search
# grounding (edith/tools/web_search.py etc.) via the genai SDK — unrelated to,
# and independent from, DEFAULT_MODEL above (the core agent's own chat model).
DEFAULT_GEMINI_GROUNDING_MODEL = "gemini-3.5-flash"

MAX_TOOL_ITERATIONS = 8
MAX_CONTEXT_TURNS = 40  # whole user->assistant/tool turns kept in the working-memory window
MAX_RESPONSE_TOKENS = 8192  # cap on each completion's max_tokens; avoids huge model defaults

DEFAULT_STT_MODEL = "openai/whisper-large-v3"
# Gemini's own native TTS (via google-genai's client.interactions.create, not
# an OpenAI-compatible call) — swapped from OpenRouter's x-ai/grok-voice-tts-1.0
# 2026-07-19 to drop the OpenRouter dependency for voice output entirely.
DEFAULT_TTS_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_TTS_VOICE = "Sulafat"  # warm female voice — closest match to the old "Eve"
MAX_RECORD_SECONDS = 120  # safety cap so /talk can't record forever if Enter is missed

GOOGLE_CLIENT_SECRET_PATH = EDITH_HOME / "google_client_secret.json"
GOOGLE_TOKEN_PATH = EDITH_HOME / "google_token.json"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

WHATSAPP_PROFILE_DIR = EDITH_HOME / "whatsapp_profile"
WHATSAPP_LOGIN_TIMEOUT_MS = 300_000  # generous window for initial multi-chat sync on first login
WHATSAPP_QR_PATH = EDITH_HOME / "whatsapp_qr.png"
# Default False to preserve today's local-CLI behavior (Sonali explicitly asked for a
# visible browser). The hosted server (no display) overrides this to true via the
# EDITH_WHATSAPP_HEADLESS env var in its deployment config.
WHATSAPP_HEADLESS = os.environ.get("EDITH_WHATSAPP_HEADLESS", "false").strip().lower() in ("1", "true", "yes")

# Not currently used by any integration — the WhatsApp-on-Browserbase migration was
# tried and reverted (see edith/whatsapp.py docstring: WhatsApp Web's persistent-storage
# requirement is denied in Browserbase's environment). Left here since the credentials
# are already saved and Browserbase may be useful for a different integration later.
BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "").strip()
BROWSERBASE_PROJECT_ID = os.environ.get("BROWSERBASE_PROJECT_ID", "").strip()
BROWSERBASE_CONTEXT_PATH = EDITH_HOME / "browserbase_context_id"

# Semantic memory (edith/memory/vectors.py). Optional, not required at startup like
# GEMINI_API_KEY/OPENROUTER_API_KEY — Qdrant Cloud credentials are provisioned
# separately, and the app should still run (just without semantic recall) if they're
# not set yet, rather than hard-failing every existing feature over a new one.
QDRANT_URL = os.environ.get("QDRANT_URL", "").strip()
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "").strip()
QDRANT_COLLECTION = "edith_memory"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 3072

# Temporal Cloud — backs schedule_job (general recurring/one-off jobs) and the nightly
# reflection schedule. Optional at startup like Qdrant: the CLI/server run fine without
# these, only `edith/temporal/worker.py` and the schedule_job tool need them, and each
# fails with a clear message rather than crashing the whole app if they're unset.
TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "").strip()
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "").strip()
TEMPORAL_API_KEY = os.environ.get("TEMPORAL_API_KEY", "").strip()
TEMPORAL_TASK_QUEUE = "edith-jobs"
NIGHTLY_REFLECTION_SCHEDULE_ID = "edith-nightly-reflection"
NIGHTLY_REFLECTION_CRON = os.environ.get("EDITH_NIGHTLY_REFLECTION_CRON", "0 3 * * *").strip()
# Unlike nightly reflection (opt-in — it's Edith taking an autonomous action on your
# behalf), this is a system health check, not agent behavior on your behalf, so the
# worker creates it unconditionally on startup (see ensure_nightly_evals_schedule in
# temporal/schedules.py) — without a regular cadence there's no time series, and
# "is Edith getting worse or better" is unanswerable from a single on-demand run.
NIGHTLY_EVALS_SCHEDULE_ID = "edith-nightly-evals"
NIGHTLY_EVALS_CRON = os.environ.get("EDITH_NIGHTLY_EVALS_CRON", "30 3 * * *").strip()

# Deep-research idea-discovery workflow (DeepResearchWorkflow in edith/temporal/workflows.py)
# — an overnight multi-round run (broad scan -> elimination -> final synthesis) that filters
# down to the best 3-4 product/startup ideas. Budget-capped since each round costs real LLM
# money; sleep hours spread the rounds across the night instead of bursting them back to back.
DEEP_RESEARCH_BUDGET_USD = float(os.environ.get("EDITH_DEEP_RESEARCH_BUDGET_USD", "1.0"))
DEEP_RESEARCH_SLEEP_HOURS = float(os.environ.get("EDITH_DEEP_RESEARCH_SLEEP_HOURS", "2"))

# Firebase Cloud Messaging (edith/push.py) — push notifications to the edith-android app
# on job completion. Optional at startup like Qdrant/Temporal: raw JSON of a Firebase
# service account, not a file path, since the Railway-hosted backend has no persistent
# filesystem for secrets but does support env vars — same var works locally and hosted.
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()

# Hunter.io (edith/tools/hunter.py) — domain search / email finder / verifier / company
# & person enrichment, for lead-gen and outreach (finding real emails to pair with the
# existing send_email tool). Optional at startup like Qdrant/Temporal/Firebase: the app
# runs fine without it, the tool just reports it isn't configured yet if called.
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "").strip()


@dataclass(frozen=True)
class Settings:
    api_key: str  # OpenRouter — the core agent's chat/tool-calling model, plus voice (STT/TTS)
    model: str  # OpenRouter model, used by the core agent's tool-calling loop
    gemini_api_key: str
    gemini_grounding_model: str  # Gemini-only, for web_search/news/youtube's native search grounding
    openrouter_text_model: str
    db_path: Path
    log_path: Path
    history_path: Path
    stt_model: str
    tts_model: str
    tts_voice: str
    qdrant_url: str
    qdrant_api_key: str
    temporal_address: str
    temporal_namespace: str
    temporal_api_key: str
    temporal_task_queue: str
    nightly_reflection_cron: str
    firebase_service_account_json: str
    hunter_api_key: str


def load_settings() -> Settings:
    EDITH_HOME.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print(
            "Error: OPENROUTER_API_KEY is not set. "
            "Copy .env.example to .env and add your key, or export it in your shell.",
            file=sys.stderr,
        )
        sys.exit(1)

    gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_api_key:
        print(
            "Error: GEMINI_API_KEY is not set. "
            "Get one at aistudio.google.com/apikey and add it to .env.",
            file=sys.stderr,
        )
        sys.exit(1)

    model = os.environ.get("EDITH_MODEL", DEFAULT_MODEL).strip()

    return Settings(
        api_key=api_key,
        model=model,
        gemini_api_key=gemini_api_key,
        gemini_grounding_model=os.environ.get("EDITH_GEMINI_GROUNDING_MODEL", DEFAULT_GEMINI_GROUNDING_MODEL).strip(),
        openrouter_text_model=os.environ.get("EDITH_OPENROUTER_TEXT_MODEL", DEFAULT_OPENROUTER_TEXT_MODEL).strip(),
        db_path=DB_PATH,
        log_path=LOG_PATH,
        history_path=HISTORY_PATH,
        stt_model=os.environ.get("EDITH_STT_MODEL", DEFAULT_STT_MODEL).strip(),
        tts_model=os.environ.get("EDITH_TTS_MODEL", DEFAULT_TTS_MODEL).strip(),
        tts_voice=os.environ.get("EDITH_TTS_VOICE", DEFAULT_TTS_VOICE).strip(),
        qdrant_url=QDRANT_URL,
        qdrant_api_key=QDRANT_API_KEY,
        temporal_address=TEMPORAL_ADDRESS,
        temporal_namespace=TEMPORAL_NAMESPACE,
        temporal_api_key=TEMPORAL_API_KEY,
        temporal_task_queue=TEMPORAL_TASK_QUEUE,
        nightly_reflection_cron=NIGHTLY_REFLECTION_CRON,
        firebase_service_account_json=FIREBASE_SERVICE_ACCOUNT_JSON,
        hunter_api_key=HUNTER_API_KEY,
    )
