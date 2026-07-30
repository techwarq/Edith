"""send_push_notification tool — lets Edith proactively push to the phone mid-
conversation (e.g. "text me when you're done with this"), not just from
scheduled jobs (see edith/temporal/activities.py for the automatic job-completion
push). Thin wrapper around edith/push.py.
"""

import sqlite3

from edith.config import Settings
from edith.push import send_push_notification as _send_push_notification
from edith.tools.registry import ToolRegistry


def register(registry: ToolRegistry, conn: sqlite3.Connection, settings: Settings) -> None:
    def send_push_notification(title: str, body: str, kind: str = "general") -> str:
        _send_push_notification(conn, settings, title, body, data={"type": kind})
        return "Push notification sent (or silently skipped if no device is registered yet)."

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "send_push_notification",
                "description": (
                    "Send a push notification to the user's phone right now. Use when the user "
                    "explicitly asks to be notified/pinged/texted about something, separately from "
                    "scheduled jobs (schedule_job/schedule_once already push automatically when "
                    "they complete)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short notification title."},
                        "body": {"type": "string", "description": "Notification body text."},
                        "kind": {
                            "type": "string",
                            "description": (
                                "Optional notification kind, default 'general'. Use 'checkin' for a "
                                "routine/todo check-in question you want the user to be able to reply "
                                "to — tapping it opens the chat instead of just replaying the last job."
                            ),
                        },
                    },
                    "required": ["title", "body"],
                },
            },
        },
        send_push_notification,
    )
