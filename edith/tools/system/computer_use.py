import logging
import os
import subprocess
from typing import Callable, Optional

from edith.computer_use import operator, screen
from edith.computer_use.typesafe_client import TypeSafeClient, TypeSafeError
from edith.config import DEFAULT_OPERATOR_MODEL, OPERATOR_MAX_STEPS, Settings
from edith.llm.client import make_client
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.tools.computer_use")

BRAVE_APP_NAME = "Brave Browser"


def register(registry: ToolRegistry, settings: Settings) -> None:
    def open_in_browser(url: str) -> str:
        url = url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            return "ERROR: open_in_browser only takes http(s) URLs."
        try:
            subprocess.run(["open", "-a", BRAVE_APP_NAME, url], check=True, timeout=10)
        except FileNotFoundError:
            return "ERROR: the macOS `open` command isn't available — this only works on Sonali's Mac."
        except subprocess.CalledProcessError as e:
            return f"ERROR: couldn't open Brave: {e}"
        return f"Opened {url} in Brave."

    operator_model = os.environ.get("EDITH_OPERATOR_MODEL", DEFAULT_OPERATOR_MODEL).strip()
    vision_client = make_client(settings.api_key) if settings.api_key else None
    try:
        jev_client: Optional[TypeSafeClient] = TypeSafeClient(settings.api_key)
    except TypeSafeError:
        jev_client = None

    def operate_mac(
        goal: str,
        allow_risky: bool = False,
        texts: Optional[list[str]] = None,
        urls: Optional[list[str]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> str:
        if vision_client is None:
            return "ERROR: no OpenRouter API key configured."
        result = operator.run(
            vision_client,
            operator_model,
            goal,
            OPERATOR_MAX_STEPS,
            allow_risky=allow_risky,
            on_progress=on_progress,
            jev=jev_client,
            texts=texts,
            urls=urls,
        )
        return result.as_text()

    def look_at_screen(question: str) -> str:
        if vision_client is None:
            return "ERROR: no OpenRouter API key configured."
        try:
            answer, path = operator.look(vision_client, operator_model, question)
        except screen.ScreenCaptureError as e:
            return f"ERROR: {e}"
        return f"{answer}\n\n(screenshot saved: {path})"

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "open_in_browser",
                "description": (
                    "Open a specific, already-known URL in Brave on Sonali's Mac (e.g. a YouTube video link "
                    "resolved by open_youtube). Use this instead of computer_use whenever you already have "
                    "the exact URL — it's instant and doesn't need any on-page interaction."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string", "description": "Full http(s) URL to open."}},
                    "required": ["url"],
                },
            },
        },
        open_in_browser,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "operate_mac",
                "description": (
                    "THE tool for anything in a named Mac app (TextEdit, Notes, Brave, Calculator, Finder…). "
                    "Actually DO something on Sonali's Mac by looking at the screen and clicking/typing like a "
                    "person: any app, any website, any setting (e.g. \"reply 'on my way' to the last WhatsApp "
                    "message from Mansfield\", \"turn on Do Not Disturb\", \"open my Downloads folder and find "
                    "the newest PDF\", \"make a new note in Notes saying ...\"). Takes screenshots each step "
                    "(saved to ~/.edith/screenshots). Pass the goal in full. Every piece of text to type or fill "
                    "must be given literally: either in double quotes inside the goal or in `texts` — the step "
                    "decider can only CHOOSE from those, never write. For forms (job/YC applications etc.), first "
                    "draft every answer, show Sonali, get her OK, then call this with all answers in `texts` and "
                    "a goal like 'fill the application form fields with the provided answers; don't submit'. "
                    "Websites to open go in `urls` (or literally in the goal). "
                    "If the result starts with NEEDS_CONFIRMATION, tell Sonali exactly what's about to happen and "
                    "ask — only after she clearly says yes, call again with the same goal and allow_risky=true. "
                    "If it starts with NEEDS_INPUT, ask her the question. Prefer open_in_browser when you just "
                    "need to open a known URL."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string", "description": "What to accomplish, in full."},
                        "texts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Exact text values available to type/fill, e.g. approved form answers.",
                        },
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Exact web addresses the task may open.",
                        },
                        "allow_risky": {
                            "type": "boolean",
                            "description": (
                                "Only true after Sonali explicitly confirmed the specific send/delete/buy/post "
                                "step this goal needs. Default false."
                            ),
                        },
                    },
                    "required": ["goal"],
                },
            },
        },
        operate_mac,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "look_at_screen",
                "description": (
                    "Take a screenshot of Sonali's Mac screen and answer a question about it — \"what's this "
                    "error?\", \"summarize this page\", \"what am I looking at?\". Read-only; doesn't click "
                    "anything. The screenshot is saved to ~/.edith/screenshots."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"question": {"type": "string", "description": "What to find out from the screen."}},
                    "required": ["question"],
                },
            },
        },
        look_at_screen,
    )
    registry.alias("computer_use", "operate_mac")
