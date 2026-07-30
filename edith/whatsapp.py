"""WhatsApp Web automation via local Playwright.

Reads and sends are on-demand only — no polling, no auto-reply, no
always-listening. Sending is gated through pending_actions (same hard-gate
pattern as edith/google/gmail.py's send_email) — execute_send_whatsapp_message
is never reachable from the LLM tool loop, only from cli.py's /approve.

Selectors: WhatsApp Web's DOM is undocumented and changes without notice.
_SELECTORS below is the single place to fix first if something breaks —
these were verified live against a real logged-in session (see project
memory), not guessed, but WhatsApp can change its markup without notice.

Browser runtime: runs locally, not on Browserbase. That migration was
attempted and reverted 2026-07-18 — WhatsApp Web calls
navigator.storage.persist() to protect its IndexedDB-stored sync/encryption
data, and Browserbase's environment denies that grant even with a real
persistent Context attached (confirmed via direct in-page diagnostic, not
guessed), so WhatsApp hangs forever at "Loading your chats". Chrome grants
persistent storage based on site-engagement heuristics a freshly-provisioned
cloud browser can never accumulate — this isn't fixable via any
browser_settings Browserbase exposes on a non-Enterprise plan. Local
Playwright doesn't hit this because a normal local Chrome profile earns
persistent-storage grants the ordinary way.

Headless mode: controlled by WHATSAPP_HEADLESS (config.py, defaults False for
local CLI use). The hosted server has no display, so its deployment config
sets EDITH_WHATSAPP_HEADLESS=true. When headless, login() can't show you a
window to scan the QR code in, so it screenshots the page and saves it to
WHATSAPP_QR_PATH — server.py serves that as a token-protected /whatsapp-qr
endpoint you open in your phone's browser instead.
"""

import logging
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from edith.config import (
    WHATSAPP_HEADLESS,
    WHATSAPP_LOGIN_TIMEOUT_MS,
    WHATSAPP_PROFILE_DIR,
    WHATSAPP_QR_PATH,
)
from edith.memory import store
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.whatsapp")

NOT_CONNECTED = "WhatsApp not connected — run /whatsapp login first."
WHATSAPP_URL = "https://web.whatsapp.com"
SESSION_LOAD_TIMEOUT_MS = 15_000
ACTION_SETTLE_MS = 800

# Verified 2026-07-18 against a real logged-in session (see project memory for how).
# The "Chat list"/"Search results." aria-label split matters: WhatsApp's default chat
# list and its post-search results list are two differently-labeled containers, and
# both need excluding the "Archived" pseudo-entry that #pane-side alone would include.
_SELECTORS = {
    "pane_side": "#pane-side",
    "qr_canvas": 'canvas[aria-label="Scan this QR code to link a device!"]',
    "search_box": 'input[aria-label="Search or start a new chat"]',
    "chat_list_item": (
        'div[aria-label="Chat list"] [data-testid="cell-frame-container"], '
        'div[aria-label="Search results."] [data-testid="cell-frame-container"]'
    ),
    "message_box": '[data-testid="conversation-compose-box-input"]',
    "send_button": 'button[aria-label="Send"]',
    "message_text": "span.selectable-text.copyable-text",
}


class WhatsAppError(Exception):
    pass


# Playwright's headless Chromium reports itself as "HeadlessChrome/<ver>" in the UA
# string, and WhatsApp Web's browser-support check rejects that outright (shows an
# "update your browser" page instead of loading). Overriding to a normal desktop
# Chrome UA fixes it — WhatsApp's check just wants Chrome 100+, not an exact match.
# Relevant again now that the hosted server runs headless.
_CHROME_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@contextmanager
def _session(headless: bool = WHATSAPP_HEADLESS) -> Iterator[Page]:
    WHATSAPP_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(WHATSAPP_PROFILE_DIR), headless=headless, user_agent=_CHROME_USER_AGENT
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            yield page
        finally:
            context.close()


def login() -> None:
    with _session() as page:
        page.goto(WHATSAPP_URL)

        if WHATSAPP_HEADLESS:
            # No local window to show a QR code in — wait for the actual QR canvas to
            # render (or for an already-logged-in profile to reach the chat list)
            # before screenshotting, so /whatsapp-qr has something scannable to serve.
            # A blind fixed delay used to run here instead and was verified live to be
            # too short sometimes — WhatsApp Web can still be on its loading splash at
            # the 3s mark (e.g. while it revalidates a previously-used persisted
            # profile), producing a screenshot with no QR code in it at all.
            try:
                page.wait_for_selector(f'{_SELECTORS["qr_canvas"]}, {_SELECTORS["pane_side"]}', timeout=15_000)
            except PlaywrightTimeoutError:
                pass  # screenshot whatever's on screen anyway — still useful for debugging
            WHATSAPP_QR_PATH.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(WHATSAPP_QR_PATH))

        try:
            page.wait_for_selector(_SELECTORS["pane_side"], timeout=WHATSAPP_LOGIN_TIMEOUT_MS)
        except PlaywrightTimeoutError as e:
            raise WhatsAppError(
                "Login timed out — QR code wasn't scanned in time. Run /whatsapp login again."
            ) from e


def _open_chat(page: Page, chat_name: str) -> bool:
    """Searches for chat_name and opens the top result. Returns False if no match."""
    search = page.query_selector(_SELECTORS["search_box"])
    if not search:
        raise WhatsAppError("Could not find the WhatsApp search box (selectors may be out of date).")
    search.click()
    page.keyboard.type(chat_name, delay=50)
    page.wait_for_timeout(ACTION_SETTLE_MS)

    first_result = page.query_selector(_SELECTORS["chat_list_item"])
    if not first_result:
        return False
    first_result.click()
    page.wait_for_timeout(ACTION_SETTLE_MS)
    return True


def whatsapp_list_chats(limit: int = 20) -> str:
    try:
        with _session() as page:
            page.goto(WHATSAPP_URL)
            try:
                page.wait_for_selector(_SELECTORS["pane_side"], timeout=SESSION_LOAD_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                return NOT_CONNECTED

            items = page.query_selector_all(_SELECTORS["chat_list_item"])[:limit]
            lines = [item.inner_text().replace("\n", " | ") for item in items]
            return "\n".join(lines) if lines else "No chats found."
    except WhatsAppError as e:
        return f"ERROR: {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("whatsapp_list_chats failed")
        return f"ERROR: WhatsApp list chats failed: {e}"


def whatsapp_read_chat(chat_name: str, limit: int = 20) -> str:
    try:
        with _session() as page:
            page.goto(WHATSAPP_URL)
            try:
                page.wait_for_selector(_SELECTORS["pane_side"], timeout=SESSION_LOAD_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                return NOT_CONNECTED

            if not _open_chat(page, chat_name):
                return f"No chat found matching '{chat_name}'."

            messages = page.query_selector_all(_SELECTORS["message_text"])[-limit:]
            texts = [m.inner_text() for m in messages]
            return "\n".join(texts) if texts else "No messages found in that chat."
    except WhatsAppError as e:
        return f"ERROR: {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("whatsapp_read_chat failed")
        return f"ERROR: WhatsApp read chat failed: {e}"


def execute_send_whatsapp_message(_auth, args: dict) -> str:
    chat_name = args["chat_name"]
    message = args["message"]
    try:
        with _session() as page:
            page.goto(WHATSAPP_URL)
            try:
                page.wait_for_selector(_SELECTORS["pane_side"], timeout=SESSION_LOAD_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                return NOT_CONNECTED

            if not _open_chat(page, chat_name):
                return f"ERROR: no chat found matching '{chat_name}' — message not sent."

            box = page.query_selector(_SELECTORS["message_box"])
            if not box:
                return "ERROR: could not find the message box (selectors may be out of date) — message not sent."
            box.click()
            page.keyboard.type(message, delay=40)  # human-paced typing, not an instant fill()
            page.wait_for_timeout(300)  # let WhatsApp's UI register the typed text before sending

            # Pressing Enter immediately after typing races WhatsApp's internal state —
            # confirmed live: the text lands in the box but nothing sends. Clicking the
            # actual Send button is reliable; Enter isn't.
            send_btn = page.query_selector(_SELECTORS["send_button"])
            if not send_btn:
                return "ERROR: could not find the Send button (selectors may be out of date) — message not sent."
            send_btn.click()
            page.wait_for_timeout(500)

            remaining = box.inner_text().strip()
            if remaining:
                return f"ERROR: message may not have sent — compose box still has text ('{remaining[:50]}')."
            return f"Message sent to '{chat_name}'."
    except WhatsAppError as e:
        return f"ERROR: {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("execute_send_whatsapp_message failed")
        return f"ERROR: sending WhatsApp message failed: {e}"


EXECUTORS = {"send_whatsapp_message": execute_send_whatsapp_message}


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def send_whatsapp_message(chat_name: str, message: str) -> str:
        action_id = store.queue_pending_action(
            conn,
            tool_name="send_whatsapp_message",
            args={"chat_name": chat_name, "message": message},
            preview=f"Send WhatsApp message to '{chat_name}'\n\n{message}",
        )
        return f"Queued as action #{action_id}. Tell the user to run /approve to review and confirm before it sends."

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "whatsapp_list_chats",
                "description": "List the user's recent WhatsApp chats (name, last message preview, time).",
                "parameters": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "description": "Max chats to return, default 20"}},
                    "required": [],
                },
            },
        },
        whatsapp_list_chats,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "whatsapp_read_chat",
                "description": "Read recent messages from a WhatsApp chat by contact/group name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chat_name": {"type": "string"},
                        "limit": {"type": "integer", "description": "Max messages to return, default 20"},
                    },
                    "required": ["chat_name"],
                },
            },
        },
        whatsapp_read_chat,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "send_whatsapp_message",
                "description": (
                    "Propose sending a WhatsApp message. This does NOT send immediately — it queues "
                    "the message for the user's review. Tell the user to run /approve to confirm "
                    "before it actually sends."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chat_name": {"type": "string"},
                        "message": {"type": "string"},
                    },
                    "required": ["chat_name", "message"],
                },
            },
        },
        send_whatsapp_message,
    )
