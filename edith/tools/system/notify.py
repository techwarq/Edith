"""send_push_notification tool — lets Edith proactively push to the phone mid-
conversation (e.g. "text me when you're done with this"), not just from
scheduled jobs (see edith/temporal/activities.py for the automatic job-completion
push). Thin wrapper around edith/push.py.
"""

from edith.integrations.push import send_push_notification as _send_push_notification
from edith.tools.base import ToolContext, tool


@tool
def send_push_notification(ctx: ToolContext, title: str, body: str, kind: str = "general") -> str:
    """Send a push notification to the user's phone right now. Use when the user
    explicitly asks to be notified/pinged/texted about something, separately from
    scheduled jobs (schedule_job/schedule_once already push automatically when
    they complete).

    Args:
        title: Short notification title.
        body: Notification body text.
        kind: Optional notification kind, default 'general'. Use 'checkin' for a
            routine/todo check-in question you want the user to be able to reply
            to — tapping it opens the chat instead of just replaying the last job.
    """
    _send_push_notification(ctx.conn, ctx.settings, title, body, data={"type": kind})
    return "Push notification sent (or silently skipped if no device is registered yet)."
