"""Calendar tools: calendar_list_events (direct), create_calendar_event
(gated via pending_actions).
"""

import logging
import sqlite3
from typing import Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from edith.google.auth import get_credentials
from edith.memory import store
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.google.calendar")

NOT_CONNECTED = "Google account not connected — run /google login first."


def _service(creds: Credentials):
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def calendar_list_events(time_min: str, time_max: str) -> str:
    creds = get_credentials()
    if not creds:
        return NOT_CONNECTED
    try:
        service = _service(creds)
        resp = (
            service.events()
            .list(calendarId="primary", timeMin=time_min, timeMax=time_max, singleEvents=True, orderBy="startTime")
            .execute()
        )
        events = resp.get("items", [])
        if not events:
            return "No events found in that range."
        lines = []
        for e in events:
            start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "?"))
            end = e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "?"))
            lines.append(f"id={e['id']} | {e.get('summary', '(no title)')} | {start} -> {end}")
        return "\n".join(lines)
    except HttpError as e:
        logger.exception("calendar_list_events failed")
        return f"ERROR: Calendar list failed: {e}"


def execute_create_calendar_event(creds: Credentials | None, args: dict) -> str:
    if not creds:
        return NOT_CONNECTED
    try:
        service = _service(creds)
        body = {
            "summary": args["summary"],
            "description": args.get("description", ""),
            "start": {"dateTime": args["start_iso"]},
            "end": {"dateTime": args["end_iso"]},
        }
        created = service.events().insert(calendarId="primary", body=body).execute()
        return f"Created event '{created.get('summary')}' (id={created.get('id')})."
    except HttpError as e:
        logger.exception("create_calendar_event execution failed")
        return f"ERROR: creating calendar event failed: {e}"


EXECUTORS: dict[str, Callable[[Credentials, dict], str]] = {
    "create_calendar_event": execute_create_calendar_event
}


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def create_calendar_event(summary: str, start_iso: str, end_iso: str, description: str = "") -> str:
        action_id = store.queue_pending_action(
            conn,
            tool_name="create_calendar_event",
            args={"summary": summary, "start_iso": start_iso, "end_iso": end_iso, "description": description},
            preview=f"Create calendar event '{summary}'\n{start_iso} -> {end_iso}\n{description}",
        )
        return f"Queued as action #{action_id}. Tell the user to run /approve to review and confirm before it's created."

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "calendar_list_events",
                "description": "List the user's calendar events in a time range.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "time_min": {"type": "string", "description": "RFC3339 timestamp, e.g. 2026-07-18T00:00:00Z"},
                        "time_max": {"type": "string", "description": "RFC3339 timestamp"},
                    },
                    "required": ["time_min", "time_max"],
                },
            },
        },
        calendar_list_events,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "create_calendar_event",
                "description": (
                    "Propose creating a calendar event. This does NOT create it immediately — it "
                    "queues the event for the user's review. Tell the user to run /approve to "
                    "confirm before it's created."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "start_iso": {"type": "string", "description": "RFC3339 timestamp"},
                        "end_iso": {"type": "string", "description": "RFC3339 timestamp"},
                        "description": {"type": "string"},
                    },
                    "required": ["summary", "start_iso", "end_iso"],
                },
            },
        },
        create_calendar_event,
    )
