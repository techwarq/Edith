"""General web browsing + form filling via Browserbase (remote browser sessions).

browse_url is a direct read tool (like drive_search/gmail_search) — inherently
live-only, no meaningful way to unit test without a real browser, same as
edith/whatsapp.py's read tools. fill_form never touches a live browser itself;
it only queues a pending_action (same hard-gate pattern as
edith/google/gmail.py's send_email) — execute_submit_form is never reachable
from the LLM tool loop, only from cli.py's /approve, since submitting a form
to a third-party site is often irreversible (job application, contact form,
purchase, etc.).

Runs on Browserbase, not local Playwright — unlike edith/whatsapp.py, this has
no persistent-login-state requirement (each browse/submit is a fresh, one-off
session), so Browserbase's cloud browsers work fine here; the
persistent-storage issue that blocked WhatsApp Web (see edith/whatsapp.py's
docstring) doesn't apply to normal page loads.
"""

import logging
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

from browserbase import Browserbase
from playwright.sync_api import Page, sync_playwright

from edith.config import BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID
from edith.memory import store
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.integrations.browse")

MAX_PAGE_TEXT_CHARS = 4000
MAX_RESULT_TEXT_CHARS = 1000
PAGE_LOAD_TIMEOUT_MS = 30_000
FIELD_FILL_TIMEOUT_MS = 5_000

NOT_CONFIGURED = "Web browsing isn't configured — BROWSERBASE_API_KEY/BROWSERBASE_PROJECT_ID aren't set."


class BrowseError(Exception):
    pass


@contextmanager
def _session() -> Iterator[Page]:
    if not BROWSERBASE_API_KEY or not BROWSERBASE_PROJECT_ID:
        raise BrowseError(NOT_CONFIGURED)
    bb = Browserbase(api_key=BROWSERBASE_API_KEY)
    bb_session = bb.sessions.create(project_id=BROWSERBASE_PROJECT_ID)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(bb_session.connect_url)
        try:
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            yield page
        finally:
            browser.close()


# Best-effort generic form-field extraction: name/type/label/placeholder for
# every input/textarea/select on the page, in or out of a <form> tag (some
# "forms" are just a handful of inputs with a JS-driven submit handler, no
# real <form> wrapper). Excludes non-fillable input types.
_EXTRACT_FIELDS_JS = """
() => {
  const fields = [];
  document.querySelectorAll('input, textarea, select').forEach(el => {
    const type = (el.tagName === 'INPUT' ? el.type : el.tagName.toLowerCase());
    if (['submit', 'button', 'hidden', 'image', 'reset'].includes(type)) return;
    let label = '';
    if (el.id) {
      const labelEl = document.querySelector(`label[for="${el.id}"]`);
      if (labelEl) label = labelEl.innerText.trim();
    }
    if (!label && el.closest('label')) label = el.closest('label').innerText.trim();
    fields.push({
      name: el.name || el.id || '',
      type,
      label,
      placeholder: el.placeholder || '',
      required: !!el.required,
    });
  });
  return fields.filter(f => f.name);
}
"""


def _find_submit_selector(page: Page) -> Optional[str]:
    for selector in ('button[type="submit"]', 'input[type="submit"]', "form button:not([type])"):
        if page.locator(selector).count() > 0:
            return selector
    return None


def browse_url(url: str) -> str:
    try:
        with _session() as page:
            page.goto(url, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="domcontentloaded")
            title = page.title()
            text = (page.evaluate("() => document.body ? document.body.innerText : ''") or "").strip()
            if len(text) > MAX_PAGE_TEXT_CHARS:
                text = text[:MAX_PAGE_TEXT_CHARS] + "\n...[truncated]"
            fields = page.evaluate(_EXTRACT_FIELDS_JS)

            result = f"Title: {title}\n\n{text}"
            if fields:
                field_lines = "\n".join(
                    f"- name={f['name']!r} type={f['type']} label={f['label']!r} "
                    f"placeholder={f['placeholder']!r} required={f['required']}"
                    for f in fields
                )
                result += f"\n\n--- This page has a form with these fields ---\n{field_lines}"
            return result
    except BrowseError as e:
        return f"ERROR: {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("browse_url failed for url=%r", url)
        return f"ERROR: browsing failed: {e}"


def execute_submit_form(_auth, args: dict) -> str:
    url = args["url"]
    field_values = args["field_values"]
    try:
        with _session() as page:
            page.goto(url, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="domcontentloaded")
            for name, value in field_values.items():
                try:
                    page.fill(f'[name="{name}"], #{name}', str(value), timeout=FIELD_FILL_TIMEOUT_MS)
                except Exception:  # noqa: BLE001 — best-effort per field; keep filling the rest
                    logger.warning("Could not fill field %r on %s", name, url)

            submit_selector = args.get("submit_selector") or _find_submit_selector(page)
            if not submit_selector:
                return "ERROR: could not find a submit button on the form."
            page.click(submit_selector, timeout=PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)

            # Title alone is often unchanged after a submit (many sites keep the same
            # <title> across a login/contact-form redirect) — a snippet of the resulting
            # page's text is what actually confirms success/failure to the user.
            result_text = (page.evaluate("() => document.body ? document.body.innerText : ''") or "").strip()
            if len(result_text) > MAX_RESULT_TEXT_CHARS:
                result_text = result_text[:MAX_RESULT_TEXT_CHARS] + "...[truncated]"
            return f"Form submitted at {url}.\nResulting page ({page.title()}):\n{result_text}"
    except Exception as e:  # noqa: BLE001
        logger.exception("execute_submit_form failed for url=%r", url)
        return f"ERROR: submitting form failed: {e}"


EXECUTORS = {"submit_form": execute_submit_form}


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def fill_form(url: str, field_values: dict) -> str:
        preview_lines = "\n".join(f"{name} = {value}" for name, value in field_values.items())
        action_id = store.queue_pending_action(
            conn,
            tool_name="submit_form",
            args={"url": url, "field_values": field_values},
            preview=f"Submit form at {url}\n\n{preview_lines}",
        )
        return f"Queued as action #{action_id}. Tell the user to run /approve to review and confirm before it's submitted."

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "browse_url",
                "description": (
                    "Visit a URL and extract its readable text content and title. If the page "
                    "contains a form, also lists the form's fields (name, type, label) so you "
                    "know what fill_form needs. Use this whenever the user shares a link and "
                    "wants details from it, or asks you to look something up on a specific page."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        browse_url,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "fill_form",
                "description": (
                    "Queue a form on a page to be filled and submitted, pending the user's approval "
                    "— never submits immediately. Call browse_url first to see what fields the form "
                    "has. Use facts you already know about the user (via recall_fact/semantic_search) "
                    "for matching fields like name/email; ask the user for anything you don't have "
                    "before calling this."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "field_values": {
                            "type": "object",
                            "description": "Map of form field name (from browse_url's field list) -> value to fill in.",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                    "required": ["url", "field_values"],
                },
            },
        },
        fill_form,
    )
