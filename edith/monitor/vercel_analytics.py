"""Vercel Web Analytics client for the Situation Monitor's Analytics panel.

Confirmed against vercel.com/docs/rest-api/web-analytics (2026-07-30):
GET https://api.vercel.com/v1/query/web-analytics/visits/count returns a
page-view count for a project over a time window, auth is a bearer token,
and projectId/teamId/since/until are query params. Vercel's published schema
for this endpoint's response is a generic shared shape (its "data" object
lists ~200 possible dimension fields spanning Vercel's whole observability
platform, not just web analytics) rather than a concrete "here's the count
field" shape, so parsing below is deliberately lenient — it tries the field
names that would make sense for a count response and raises a clear,
distinguishable error if none match, rather than guessing wrong silently.
There is no separate "unique visitors" count endpoint in the docs, only page
views — so this reports page views, not visitors, and says so.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger("edith.monitor.vercel_analytics")

_BASE_URL = "https://api.vercel.com"
_TIMEOUT_SECONDS = 15
_COUNT_FIELD_CANDIDATES = ("count", "value", "total", "visits", "pageViews", "pageviews")


class VercelAnalyticsError(Exception):
    pass


def _extract_count(data: Any) -> Optional[int]:
    if isinstance(data, (int, float)):
        return int(data)
    if isinstance(data, dict):
        for key in _COUNT_FIELD_CANDIDATES:
            if key in data and isinstance(data[key], (int, float)):
                return int(data[key])
        # Fallback: a single numeric leaf value anywhere in the object is
        # almost certainly the count on a scalar "counts page views" query.
        numeric_values = [v for v in data.values() if isinstance(v, (int, float))]
        if len(numeric_values) == 1:
            return int(numeric_values[0])
    if isinstance(data, list) and data:
        total = 0
        found = False
        for row in data:
            row_count = _extract_count(row) if isinstance(row, dict) else None
            if row_count is not None:
                total += row_count
                found = True
        if found:
            return total
    return None


def get_pageview_summary(token: str, project_id: str, team_id: str = "", days: int = 30) -> dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    until = datetime.now(timezone.utc).isoformat()
    params = {"projectId": project_id, "since": since, "until": until}
    if team_id:
        params["teamId"] = team_id

    try:
        resp = requests.get(
            f"{_BASE_URL}/v1/query/web-analytics/visits/count",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        raise VercelAnalyticsError(f"network error calling Vercel: {e}") from e

    if resp.status_code >= 400:
        raise VercelAnalyticsError(f"Vercel Analytics API error ({resp.status_code}): {resp.text[:300]}")
    try:
        body = resp.json()
    except ValueError as e:
        raise VercelAnalyticsError(f"Vercel returned a non-JSON response (status {resp.status_code})") from e

    count = _extract_count(body.get("data"))
    if count is None:
        raise VercelAnalyticsError(
            "Couldn't find a count in Vercel's response — its shape may not match what this integration expects."
        )

    return {"configured": True, "pageviews": count, "days": days, "fetched_at": datetime.now(timezone.utc).isoformat()}
