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
DEFAULT_MODEL = "qwen/qwen3.7-flash"
DEFAULT_OPENROUTER_TEXT_MODEL = "qwen/qwen3-coder-next"
DEFAULT_STARTUP_FINDER_MODEL = "meta/muse-spark-1.3"
DEFAULT_STARTUP_FINDER_FALLBACK_MODEL = "qwen/qwen3.8-flash"
DEFAULT_GEMINI_GROUNDING_MODEL = "gemini-3.5-flash"

MAX_TOOL_ITERATIONS = 8
MAX_CONTEXT_TURNS = 40
MAX_RESPONSE_TOKENS = 8192

DEFAULT_STT_MODEL = "openai/whisper-large-v3"
DEFAULT_TTS_MODEL = "hexgrad/kokoro-82m"
DEFAULT_TTS_VOICE = "af_heart"
MAX_RECORD_SECONDS = 120

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
WHATSAPP_LOGIN_TIMEOUT_MS = 300_000
WHATSAPP_QR_PATH = EDITH_HOME / "whatsapp_qr.png"
WHATSAPP_HEADLESS = os.environ.get("EDITH_WHATSAPP_HEADLESS", "false").strip().lower() in ("1", "true", "yes")

BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "").strip()
BROWSERBASE_PROJECT_ID = os.environ.get("BROWSERBASE_PROJECT_ID", "").strip()
BROWSERBASE_CONTEXT_PATH = EDITH_HOME / "browserbase_context_id"

QDRANT_URL = os.environ.get("QDRANT_URL", "").strip()
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "").strip()
QDRANT_COLLECTION = "edith_memory"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 3072

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "").strip()
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "").strip()
TEMPORAL_API_KEY = os.environ.get("TEMPORAL_API_KEY", "").strip()
TEMPORAL_TASK_QUEUE = "edith-jobs"
NIGHTLY_REFLECTION_SCHEDULE_ID = "edith-nightly-reflection"
NIGHTLY_REFLECTION_CRON = os.environ.get("EDITH_NIGHTLY_REFLECTION_CRON", "0 3 * * *").strip()
NIGHTLY_EVALS_SCHEDULE_ID = "edith-nightly-evals"
NIGHTLY_EVALS_CRON = os.environ.get("EDITH_NIGHTLY_EVALS_CRON", "30 3 * * *").strip()

DEEP_RESEARCH_BUDGET_USD = float(os.environ.get("EDITH_DEEP_RESEARCH_BUDGET_USD", "1.0"))
DEEP_RESEARCH_SLEEP_HOURS = float(os.environ.get("EDITH_DEEP_RESEARCH_SLEEP_HOURS", "2"))

FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "").strip()
CRUSTDATA_API_KEY = os.environ.get("CRUSTDATA_API_KEY", "").strip()
APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "").strip()
PROSPEO_API_KEY = os.environ.get("PROSPEO_API_KEY", "").strip()
RESUME_PDF = os.environ.get("EDITH_RESUME_PDF", str(EDITH_HOME / "resume.pdf")).strip()

DODO_PAYMENTS_API_KEY = os.environ.get("DODO_PAYMENTS_API_KEY", "").strip()
DODO_PAYMENTS_BASE_URL = os.environ.get("DODO_PAYMENTS_BASE_URL", "https://live.dodopayments.com").strip()

VERCEL_ANALYTICS_TOKEN = os.environ.get("VERCEL_ANALYTICS_TOKEN", "").strip()
VERCEL_TEAM_ID = os.environ.get("VERCEL_TEAM_ID", "").strip()

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

JOB_SEARCH_SCHEDULE_ID = "edith-job-search"
JOB_SEARCH_CRON = os.environ.get("EDITH_JOB_SEARCH_CRON", "30 4-13 * * 1-5").strip()
JOB_SEARCH_LEADS_PER_RUN = int(os.environ.get("EDITH_JOB_SEARCH_LEADS_PER_RUN", "3"))
JOBS_DAILY_CAP = int(os.environ.get("EDITH_JOBS_DAILY_CAP", "25"))

LINKEDIN_TEXT_MODEL = os.environ.get("LINKEDIN_TEXT_MODEL", "qwen/qwen3.7-flash").strip()
LINKEDIN_FALLBACK_TEXT_MODEL = os.environ.get("LINKEDIN_FALLBACK_TEXT_MODEL", "qwen/qwen3.5-flash-02-23").strip()
LINKEDIN_IMAGE_MODEL = os.environ.get("LINKEDIN_IMAGE_MODEL", "meta/muse-image").strip()
LINKEDIN_FALLBACK_IMAGE_MODEL = os.environ.get("LINKEDIN_FALLBACK_IMAGE_MODEL", "google/gemini-2.5-flash-image").strip()
LINKEDIN_CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "").strip()
LINKEDIN_CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "").strip()
LINKEDIN_REDIRECT_URI = os.environ.get("LINKEDIN_REDIRECT_URI", "").strip()
LINKEDIN_VERSION = os.environ.get("LINKEDIN_VERSION", "202607").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
PGVECTOR_ENABLED = os.environ.get("PGVECTOR_ENABLED", "true").strip().lower() not in ("0", "false", "no")

DEFAULT_COMPUTER_USE_WRITER_MODEL = "qwen/qwen3.7-flash"
DEFAULT_OPERATOR_MODEL = "google/gemini-3.8-flash"
OPERATOR_MAX_STEPS = int(os.environ.get("EDITH_OPERATOR_MAX_STEPS", "40"))
COMPUTER_USE_MAX_STEPS = int(os.environ.get("EDITH_COMPUTER_USE_MAX_STEPS", "12"))
COMPUTER_USE_CONFIDENCE_THRESHOLD = float(os.environ.get("EDITH_COMPUTER_USE_CONFIDENCE_THRESHOLD", "0.5"))


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    gemini_api_key: str
    gemini_grounding_model: str
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
    dodo_payments_api_key: str
    dodo_payments_base_url: str
    vercel_analytics_token: str
    vercel_team_id: str
    github_token: str
    linkedin_text_model: str
    linkedin_fallback_text_model: str
    linkedin_image_model: str
    linkedin_fallback_image_model: str
    linkedin_client_id: str
    linkedin_client_secret: str
    linkedin_redirect_uri: str
    linkedin_version: str
    database_url: str
    pgvector_enabled: bool
    computer_use_writer_model: str
    computer_use_max_steps: int
    computer_use_confidence_threshold: float
    crustdata_api_key: str = ""
    resume_pdf: str = ""
    apollo_api_key: str = ""
    prospeo_api_key: str = ""
    startup_finder_model: str = DEFAULT_STARTUP_FINDER_MODEL
    startup_finder_fallback_model: str = DEFAULT_STARTUP_FINDER_FALLBACK_MODEL


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
        crustdata_api_key=CRUSTDATA_API_KEY,
        resume_pdf=RESUME_PDF,
        apollo_api_key=APOLLO_API_KEY,
        prospeo_api_key=PROSPEO_API_KEY,
        startup_finder_model=os.environ.get("EDITH_STARTUP_FINDER_MODEL", DEFAULT_STARTUP_FINDER_MODEL).strip(),
        startup_finder_fallback_model=os.environ.get("EDITH_STARTUP_FINDER_FALLBACK_MODEL", DEFAULT_STARTUP_FINDER_FALLBACK_MODEL).strip(),
        dodo_payments_api_key=DODO_PAYMENTS_API_KEY,
        dodo_payments_base_url=DODO_PAYMENTS_BASE_URL,
        vercel_analytics_token=VERCEL_ANALYTICS_TOKEN,
        vercel_team_id=VERCEL_TEAM_ID,
        github_token=GITHUB_TOKEN,
        linkedin_text_model=LINKEDIN_TEXT_MODEL,
        linkedin_fallback_text_model=LINKEDIN_FALLBACK_TEXT_MODEL,
        linkedin_image_model=LINKEDIN_IMAGE_MODEL,
        linkedin_fallback_image_model=LINKEDIN_FALLBACK_IMAGE_MODEL,
        linkedin_client_id=LINKEDIN_CLIENT_ID,
        linkedin_client_secret=LINKEDIN_CLIENT_SECRET,
        linkedin_redirect_uri=LINKEDIN_REDIRECT_URI,
        linkedin_version=LINKEDIN_VERSION,
        database_url=DATABASE_URL,
        pgvector_enabled=PGVECTOR_ENABLED,
        computer_use_writer_model=os.environ.get(
            "EDITH_COMPUTER_USE_WRITER_MODEL", DEFAULT_COMPUTER_USE_WRITER_MODEL
        ).strip(),
        computer_use_max_steps=COMPUTER_USE_MAX_STEPS,
        computer_use_confidence_threshold=COMPUTER_USE_CONFIDENCE_THRESHOLD,
    )
