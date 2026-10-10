import logging
import threading
import time
from typing import Any, Optional

import requests

logger = logging.getLogger("edith.startup_finder.prospeo")

BASE_URL = "https://api.prospeo.io"
TIMEOUT = 30
GOOD_STATUSES = ("VERIFIED",)


class ProspeoError(Exception):
    pass


class ProspeoQuotaError(ProspeoError):
    pass


RETRIES = 4
_lock = threading.Lock()
_last_call = 0.0
MIN_INTERVAL = 1.1


def _throttled_post(api_key: str, path: str, body: dict[str, Any]) -> requests.Response:
    global _last_call
    with _lock:
        wait = _last_call + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    return requests.post(f"{BASE_URL}/{path}", json=body, timeout=TIMEOUT,
                         headers={"X-KEY": api_key, "Content-Type": "application/json"})


def _post(api_key: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(RETRIES):
        try:
            resp = _throttled_post(api_key, path, body)
        except requests.exceptions.RequestException as e:
            raise ProspeoError(f"network error calling Prospeo: {e}") from e
        if resp.status_code != 429:
            break
        time.sleep(2 * (attempt + 1))
    else:
        raise ProspeoError("Prospeo rate limit — try again shortly")
    try:
        data = resp.json()
    except ValueError as e:
        raise ProspeoError(f"Prospeo returned non-JSON (status {resp.status_code})") from e
    code = str(data.get("error_code") or "")
    if code == "INSUFFICIENT_CREDITS":
        raise ProspeoQuotaError("Prospeo is out of credits")
    if resp.status_code >= 400 or data.get("error"):
        raise ProspeoError(f"Prospeo error ({resp.status_code}): {code or resp.text[:200]}")
    return data


def enrich(api_key: str, domain: str, name: Optional[str] = None, linkedin: Optional[str] = None) -> Optional[dict[str, Any]]:
    data: dict[str, Any] = {"company_website": domain}
    if linkedin:
        data["linkedin_url"] = linkedin
    if name:
        data["full_name"] = name
    try:
        resp = _post(api_key, "enrich-person", {"only_verified_email": True, "data": data})
    except ProspeoQuotaError:
        raise
    except ProspeoError as e:
        logger.info("prospeo enrich failed for %s @ %s: %s", name or linkedin, domain, e)
        return None
    person = resp.get("person") or {}
    email = person.get("email") or {}
    if not person:
        return None
    return {
        "name": person.get("full_name") or name,
        "title": person.get("current_job_title"),
        "email": email.get("email") if email.get("status") in GOOD_STATUSES else None,
        "email_status": (email.get("status") or "").lower() or None,
        "linkedin": person.get("linkedin_url"),
        "source": "prospeo",
    }
