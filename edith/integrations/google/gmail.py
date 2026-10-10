"""Gmail tools: gmail_search/gmail_read (direct), send_email (gated via
pending_actions — see edith/memory/store.py's queue_pending_action).
"""

import base64
import logging
import sqlite3
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Callable, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from edith.integrations.google.auth import get_credentials
from edith.memory import store
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.integrations.google.gmail")

NOT_CONNECTED = "Google account not connected — run /google login first."


def _service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text
    return ""


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def gmail_search(query: str) -> str:
    creds = get_credentials()
    if not creds:
        return NOT_CONNECTED
    try:
        service = _service(creds)
        resp = service.users().messages().list(userId="me", q=query, maxResults=10).execute()
        messages = resp.get("messages", [])
        if not messages:
            return "No matching emails found."
        lines = []
        for m in messages:
            meta = (
                service.users()
                .messages()
                .get(userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
            headers = meta.get("payload", {}).get("headers", [])
            lines.append(
                f"id={m['id']} | From: {_header(headers, 'From')} | "
                f"Subject: {_header(headers, 'Subject')} | Date: {_header(headers, 'Date')} | "
                f"{meta.get('snippet', '')}"
            )
        return "\n".join(lines)
    except HttpError as e:
        logger.exception("gmail_search failed")
        return f"ERROR: Gmail search failed: {e}"


def gmail_read(message_id: str) -> str:
    creds = get_credentials()
    if not creds:
        return NOT_CONNECTED
    try:
        service = _service(creds)
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = msg.get("payload", {}).get("headers", [])
        body = _extract_body(msg.get("payload", {})) or msg.get("snippet", "")
        return (
            f"From: {_header(headers, 'From')}\n"
            f"Subject: {_header(headers, 'Subject')}\n"
            f"Date: {_header(headers, 'Date')}\n\n"
            f"{body}"
        )
    except HttpError as e:
        logger.exception("gmail_read failed")
        return f"ERROR: Gmail read failed: {e}"


def execute_send_email(creds: Credentials | None, args: dict) -> str:
    if not creds:
        return NOT_CONNECTED
    try:
        service = _service(creds)
        message = MIMEText(args["body"])
        message["to"] = args["to"]
        message["subject"] = args["subject"]
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"Email sent to {args['to']}."
    except HttpError as e:
        logger.exception("send_email execution failed")
        return f"ERROR: sending email failed: {e}"


def send_rich_email(creds: Credentials | None, to: str, subject: str, text: str, html: str, attachment: Optional[Path] = None, attachment_name: Optional[str] = None) -> str:
    if not creds:
        return NOT_CONNECTED
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text, "plain", "utf-8"))
    alt.attach(MIMEText(html, "html", "utf-8"))
    if attachment:
        message = MIMEMultipart("mixed")
        message.attach(alt)
        part = MIMEApplication(attachment.read_bytes(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=attachment_name or attachment.name)
        message.attach(part)
    else:
        message = alt
    message["to"] = to
    message["subject"] = subject
    try:
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        _service(creds).users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"Email sent to {to}."
    except HttpError as e:
        logger.exception("send_rich_email failed")
        return f"ERROR: sending email failed: {e}"


EXECUTORS: dict[str, Callable[[Credentials, dict], str]] = {"send_email": execute_send_email}


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def send_email(to: str, subject: str, body: str) -> str:
        action_id = store.queue_pending_action(
            conn,
            tool_name="send_email",
            args={"to": to, "subject": subject, "body": body},
            preview=f"Send email to {to}\nSubject: {subject}\n\n{body}",
        )
        return f"Queued as action #{action_id}. Tell the user to run /approve to review and confirm before it sends."

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "gmail_search",
                "description": "Search the user's Gmail using Gmail search syntax (e.g. 'from:x subject:y is:unread').",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        gmail_search,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "gmail_read",
                "description": "Read the full content of a single Gmail message by its id (from gmail_search results).",
                "parameters": {
                    "type": "object",
                    "properties": {"message_id": {"type": "string"}},
                    "required": ["message_id"],
                },
            },
        },
        gmail_read,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "send_email",
                "description": (
                    "Propose sending an email. This does NOT send immediately — it queues the "
                    "email for the user's review. Tell the user to run /approve to confirm before "
                    "it actually sends."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
        },
        send_email,
    )
