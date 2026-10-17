"""get_health_summary tool — read-only access to synced Health Connect data
(edith/memory/planning.py). No write tool here: metrics only ever come in via
the Android app's own sync (POST /api/health-data), never from the LLM.
"""

from edith.memory.records import planning
from edith.tools.base import ToolContext, tool


@tool
def get_health_summary(ctx: ToolContext) -> str:
    """Get a summary of the user's synced health data — latest weight, recent
    average steps, active calories, and workout count. Use this when the user
    asks about their weight, steps, fitness, or health goal progress, instead
    of guessing or saying you don't have access.
    """
    return planning.summarize_health(ctx.conn)
