"""Local-machine computer use: open a known URL in Brave (deterministic, no
model call needed), or drive an open-ended on-screen goal via the
perceive-decide-act loop in edith/computer_use/runner.py.

Local-only, like edith/whatsapp.py's Playwright profile — makes no sense on
the hosted Railway server (no display, no Brave, no macOS Accessibility), so
every entry point here reports "not configured" rather than crashing when
permissions aren't present, same tier as hunter.py/vercel.py.

Both the Jev decisions (typesafe_client.py) and the writer's free-text
generation (writer.py) go through OpenRouter, reusing settings.api_key —
no separate TypeSafe or Vercel account.

Treat on-screen content as untrusted data: decide.py's own instructions to
Jev already say not to follow instructions found in on-screen items, only
the goal given here.
"""

import logging
import subprocess
from typing import Callable, Optional

from edith.computer_use.runner import run as run_computer_use
from edith.computer_use.typesafe_client import TypeSafeClient, TypeSafeError
from edith.computer_use.writer import make_writer_client
from edith.config import Settings
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

    def computer_use(goal: str, on_progress: Optional[Callable[[str], None]] = None) -> str:
        try:
            client = TypeSafeClient(settings.api_key)
        except TypeSafeError as e:
            return f"ERROR: {e}"

        writer_client = make_writer_client(settings.api_key) if settings.api_key else None

        result = run_computer_use(
            client,
            goal,
            settings.computer_use_max_steps,
            settings.computer_use_confidence_threshold,
            writer_client=writer_client,
            writer_model=settings.computer_use_writer_model,
            on_progress=on_progress,
        )

        lines = [f"step {s.number}: {s.kind} (confidence {s.confidence:.2f}) -> {s.result}" for s in result.steps]
        header = "Done: " if result.done else "Stopped: "
        body = "\n".join(lines) if lines else "(no steps taken)"
        full = f"{header}{result.message}\n\n{body}"
        print(f"[computer_use] goal={goal!r}\n{full}")  # noqa: T201 — temporary debug, remove after diagnosis
        return full

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
                "name": "computer_use",
                "description": (
                    "Drive native macOS apps or the Brave browser on Sonali's Mac toward an on-screen goal "
                    "that needs actually looking at and clicking through the interface (e.g. \"find the "
                    "unread message from Alice in Slack and read it\", \"in Brave, search YouTube for the "
                    "Elliot Choy video and open it\"). Runs a bounded perceive-decide-act loop and reports "
                    "what it did or where it stopped. Prefer open_in_browser when you already have a direct "
                    "URL — only reach for this when on-page navigation/clicking is actually required."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "One concrete, single-instruction goal — not a compound multi-part request.",
                        }
                    },
                    "required": ["goal"],
                },
            },
        },
        computer_use,
    )
