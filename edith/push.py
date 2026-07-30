"""Firebase Cloud Messaging push notifications to the edith-android app.

Optional integration, same degrade-gracefully pattern as Qdrant/Temporal
(edith/temporal/client.py's TemporalNotConfigured): if FIREBASE_SERVICE_ACCOUNT_JSON
isn't set, or no device has registered a token yet, send_push_notification is a
logged no-op rather than a raised error — a job or tool call that happens to also
want to notify shouldn't fail over notification plumbing being unset.
"""

import json
import logging
import sqlite3

import firebase_admin
from firebase_admin import credentials, messaging

from edith.config import Settings
from edith.memory import store

logger = logging.getLogger("edith.push")

_app: firebase_admin.App | None = None


def _get_app(settings: Settings) -> firebase_admin.App | None:
    global _app
    if _app is not None:
        return _app
    if not settings.firebase_service_account_json:
        return None
    cred = credentials.Certificate(json.loads(settings.firebase_service_account_json))
    _app = firebase_admin.initialize_app(cred)
    return _app


def send_push_notification(
    conn: sqlite3.Connection,
    settings: Settings,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> None:
    app = _get_app(settings)
    if app is None:
        logger.info("Push notification skipped (FIREBASE_SERVICE_ACCOUNT_JSON not set): %s", title)
        return

    tokens = store.list_device_tokens(conn)
    if not tokens:
        logger.info("Push notification skipped (no registered devices): %s", title)
        return

    for token in tokens:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=data,
            token=token,
        )
        try:
            message_id = messaging.send(message, app=app)
            logger.info("Push notification sent: %s", message_id)
        except (messaging.UnregisteredError, ValueError):
            logger.info("Pruning stale/invalid device token")
            store.delete_device_token(conn, token)
        except Exception:
            logger.exception("Failed to send push notification to a device")
