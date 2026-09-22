"""Docs/Sheets tools. Docs stays read-only (its batchUpdate API is a much
bigger, fussier surface — still deferred). Sheets now has write support
(sheets_append_row/sheets_update_cell) via the simpler values().append/update
endpoints, which don't need batchUpdate at all.

Unlike Gmail/Drive/Calendar writes, Sheets writes are NOT gated through
pending_actions/approve — they only ever touch a spreadsheet the user
already owns and named, appending/overwriting cells is trivially reversible
(undo in Sheets, or just edit it back), and gating would break the whole
point of unattended scheduled jobs that read+update a tracking sheet (a
9am job has nobody around to run /approve). Email/calendar/Drive-file writes
stay gated because they're irreversible or externally visible in a way a
spreadsheet cell isn't.
"""

import logging
import sqlite3

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from edith.integrations.google.auth import get_credentials
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.integrations.google.docs_sheets")

NOT_CONNECTED = "Google account not connected — run /google login first."
MAX_READ_CHARS = 5000


def _extract_doc_text(body: dict) -> str:
    parts = []
    for element in body.get("content", []):
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        for el in paragraph.get("elements", []):
            text_run = el.get("textRun")
            if text_run:
                parts.append(text_run.get("content", ""))
    return "".join(parts)


def docs_read(document_id: str) -> str:
    creds = get_credentials()
    if not creds:
        return NOT_CONNECTED
    try:
        service = build("docs", "v1", credentials=creds, cache_discovery=False)
        doc = service.documents().get(documentId=document_id).execute()
        text = _extract_doc_text(doc.get("body", {}))
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + "\n...[truncated]"
        return f"{doc.get('title', '(untitled)')}:\n\n{text}"
    except HttpError as e:
        logger.exception("docs_read failed")
        return f"ERROR: Docs read failed: {e}"


def sheets_read(spreadsheet_id: str, range: str) -> str:  # noqa: A002 - matches Sheets API param name
    creds = get_credentials()
    if not creds:
        return NOT_CONNECTED
    try:
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        resp = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range).execute()
        values = resp.get("values", [])
        if not values:
            return "No data found in that range."
        text = "\n".join("\t".join(str(cell) for cell in row) for row in values)
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + "\n...[truncated]"
        return text
    except HttpError as e:
        logger.exception("sheets_read failed")
        return f"ERROR: Sheets read failed: {e}"


def sheets_append_row(spreadsheet_id: str, range: str, values: list[str]) -> str:  # noqa: A002 - matches Sheets API param name
    creds = get_credentials()
    if not creds:
        return NOT_CONNECTED
    try:
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [values]},
        ).execute()
        return f"Appended row to {range}: {values}"
    except HttpError as e:
        logger.exception("sheets_append_row failed")
        return f"ERROR: Sheets append failed: {e}"


def sheets_update_cell(spreadsheet_id: str, range: str, values: list[str]) -> str:  # noqa: A002 - matches Sheets API param name
    creds = get_credentials()
    if not creds:
        return NOT_CONNECTED
    try:
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range,
            valueInputOption="USER_ENTERED",
            body={"values": [values]},
        ).execute()
        return f"Updated {range}: {values}"
    except HttpError as e:
        logger.exception("sheets_update_cell failed")
        return f"ERROR: Sheets update failed: {e}"


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:  # noqa: ARG001 - conn kept for signature consistency with other register()s
    registry.register(
        {
            "type": "function",
            "function": {
                "name": "docs_read",
                "description": "Read the text content of a Google Doc by its document id.",
                "parameters": {
                    "type": "object",
                    "properties": {"document_id": {"type": "string"}},
                    "required": ["document_id"],
                },
            },
        },
        docs_read,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "sheets_read",
                "description": "Read a cell range from a Google Sheet, e.g. range='Sheet1!A1:D20'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {"type": "string"},
                        "range": {"type": "string"},
                    },
                    "required": ["spreadsheet_id", "range"],
                },
            },
        },
        sheets_read,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "sheets_append_row",
                "description": (
                    "Append a new row to the end of the data in a Google Sheet range, e.g. "
                    "range='Sheet1!A:D'. Use this to add new entries (like new questions/tasks) "
                    "without overwriting existing rows."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {"type": "string"},
                        "range": {"type": "string", "description": "Sheet name or range to append within, e.g. 'Sheet1!A:D'"},
                        "values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "The row's cell values in order, e.g. ['Q1', 'What is a closure?', 'Not started']",
                        },
                    },
                    "required": ["spreadsheet_id", "range", "values"],
                },
            },
        },
        sheets_append_row,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "sheets_update_cell",
                "description": (
                    "Overwrite specific cell(s) in a Google Sheet, e.g. range='Sheet1!C5' for one "
                    "cell or 'Sheet1!C5:D5' for a few in a row. Use this to mark a row completed, "
                    "update a status, or leave a comment in an existing row — not for adding new rows."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {"type": "string"},
                        "range": {"type": "string", "description": "Exact cell or cell range to overwrite, e.g. 'Sheet1!C5:D5'"},
                        "values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Values to write, one per cell in the range, in order",
                        },
                    },
                    "required": ["spreadsheet_id", "range", "values"],
                },
            },
        },
        sheets_update_cell,
    )
