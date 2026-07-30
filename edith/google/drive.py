"""Drive tools: drive_search/drive_read_file (direct), create_drive_file
(gated via pending_actions).
"""

import io
import logging
import sqlite3
from typing import Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from edith.google.auth import get_credentials
from edith.memory import store
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.google.drive")

NOT_CONNECTED = "Google account not connected — run /google login first."
MAX_READ_CHARS = 5000


def _service(creds: Credentials):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _escape_query(query: str) -> str:
    return query.replace("\\", "\\\\").replace("'", "\\'")


def drive_search(query: str) -> str:
    creds = get_credentials()
    if not creds:
        return NOT_CONNECTED
    try:
        service = _service(creds)
        escaped = _escape_query(query)
        resp = (
            service.files()
            .list(
                q=f"fullText contains '{escaped}' and trashed=false",
                pageSize=10,
                fields="files(id,name,mimeType,modifiedTime)",
            )
            .execute()
        )
        files = resp.get("files", [])
        if not files:
            return "No matching Drive files found."
        return "\n".join(
            f"id={f['id']} | {f['name']} | {f['mimeType']} | modified {f['modifiedTime']}" for f in files
        )
    except HttpError as e:
        logger.exception("drive_search failed")
        return f"ERROR: Drive search failed: {e}"


def drive_read_file(file_id: str) -> str:
    creds = get_credentials()
    if not creds:
        return NOT_CONNECTED
    try:
        service = _service(creds)
        meta = service.files().get(fileId=file_id, fields="id,name,mimeType").execute()
        mime_type = meta["mimeType"]

        if mime_type.startswith("application/vnd.google-apps."):
            content = service.files().export_media(fileId=file_id, mimeType="text/plain").execute()
        else:
            content = service.files().get_media(fileId=file_id).execute()

        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + "\n...[truncated]"
        return f"{meta['name']} ({mime_type}):\n\n{text}"
    except HttpError as e:
        logger.exception("drive_read_file failed")
        return f"ERROR: Drive read failed: {e}"


def execute_create_drive_file(creds: Credentials | None, args: dict) -> str:
    if not creds:
        return NOT_CONNECTED
    try:
        service = _service(creds)
        mime_type = args.get("mime_type") or "text/plain"
        media = MediaIoBaseUpload(io.BytesIO(args["content"].encode("utf-8")), mimetype=mime_type)
        created = service.files().create(body={"name": args["name"]}, media_body=media, fields="id,name").execute()
        return f"Created Drive file '{created['name']}' (id={created['id']})."
    except HttpError as e:
        logger.exception("create_drive_file execution failed")
        return f"ERROR: creating Drive file failed: {e}"


EXECUTORS: dict[str, Callable[[Credentials, dict], str]] = {"create_drive_file": execute_create_drive_file}


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def create_drive_file(name: str, content: str, mime_type: str = "text/plain") -> str:
        action_id = store.queue_pending_action(
            conn,
            tool_name="create_drive_file",
            args={"name": name, "content": content, "mime_type": mime_type},
            preview=f"Create Drive file '{name}' ({mime_type})\n\n{content[:500]}",
        )
        return f"Queued as action #{action_id}. Tell the user to run /approve to review and confirm before it's created."

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "drive_search",
                "description": "Full-text search the user's Google Drive files by content or name.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        drive_search,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "drive_read_file",
                "description": "Read the text content of a Drive file by id (from drive_search results). Google Docs/Sheets/Slides are exported as plain text.",
                "parameters": {
                    "type": "object",
                    "properties": {"file_id": {"type": "string"}},
                    "required": ["file_id"],
                },
            },
        },
        drive_read_file,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "create_drive_file",
                "description": (
                    "Propose creating a new plain text/markdown file in the user's Drive. "
                    "This does NOT create it immediately — it queues the file for the user's "
                    "review. Tell the user to run /approve to confirm before it's created."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                        "mime_type": {"type": "string", "description": "Defaults to text/plain"},
                    },
                    "required": ["name", "content"],
                },
            },
        },
        create_drive_file,
    )
