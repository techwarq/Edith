"""Career plugin — job-application pipeline, startup finder + cold email, founder
outreach, Hunter email lookup, and the LinkedIn/X content planner. Opt-in with
EDITH_PLUGINS=career; everything personal comes from the career profile
(profile.py), never from code."""

import sqlite3
from typing import Any

NAME = "career"


def tool_modules() -> list[Any]:
    from edith.plugins.career import pipeline
    from edith.plugins.career.tools import hunter, job_applications, outreach, startup_finder

    return [hunter, job_applications, outreach, startup_finder, pipeline]


def setup(conn: sqlite3.Connection) -> None:
    from edith.plugins.career.tools import job_applications

    job_applications.seed_job_sources(conn)


def ensure_schema(conn: sqlite3.Connection) -> None:
    from edith.plugins.career import store
    from edith.plugins.career.linkedin.store import LINKEDIN_SCHEMA

    store.ensure_schema(conn)
    conn.executescript(LINKEDIN_SCHEMA)


def routers(conn: sqlite3.Connection, settings: Any, genai_client: Any, api_token: str) -> list[Any]:
    from edith.plugins.career.job_applications import api as job_applications_api
    from edith.plugins.career.linkedin import api as linkedin_api
    from edith.plugins.career.startup_finder import api as startup_finder_api

    return [
        job_applications_api.build_router(conn, api_token),
        startup_finder_api.build_router(conn, settings, genai_client, api_token),
        linkedin_api.build_router(conn, genai_client, api_token),
    ]
