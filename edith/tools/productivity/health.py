"""get_health_summary tool — read-only access to synced Health Connect data
(edith/memory/health.py). No write tool here: metrics only ever come in via
the Android app's own sync (POST /api/health-data), never from the LLM.
"""

import sqlite3

from edith.memory import health
from edith.tools.registry import ToolRegistry


def register(registry: ToolRegistry, conn: sqlite3.Connection) -> None:
    def get_health_summary() -> str:
        return health.summarize(conn)

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "get_health_summary",
                "description": (
                    "Get a summary of the user's synced health data — latest weight, recent "
                    "average steps, active calories, and workout count. Use this when the user "
                    "asks about their weight, steps, fitness, or health goal progress, instead "
                    "of guessing or saying you don't have access."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        get_health_summary,
    )
