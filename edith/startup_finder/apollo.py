import logging
import re
from typing import Any, Optional

import requests

logger = logging.getLogger("edith.startup_finder.apollo")

BASE_URL = "https://api.apollo.io/api/v1"
TIMEOUT = 30
GOOD_STATUSES = ("verified", "likely to engage")
LEADER_SENIORITIES = ["owner", "founder", "c_suite", "head", "vp"]


class ApolloError(Exception):
    pass


class ApolloQuotaError(ApolloError):
    pass


def _post(api_key: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = requests.post(
            f"{BASE_URL}/{path}",
            json=body,
            headers={"x-api-key": api_key, "content-type": "application/json", "cache-control": "no-cache"},
            timeout=TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        raise ApolloError(f"network error calling Apollo: {e}") from e
    try:
        data = resp.json()
    except ValueError as e:
        raise ApolloError(f"Apollo returned non-JSON (status {resp.status_code})") from e
    if resp.status_code in (402, 422, 429) and re.search(r"credit|limit|quota", resp.text, re.I):
        raise ApolloQuotaError("Apollo is out of credits")
    if resp.status_code >= 400:
        raise ApolloError(f"Apollo API error ({resp.status_code}): {data.get('error') or data.get('message') or resp.text[:200]}")
    return data


def _person(p: dict[str, Any]) -> Optional[dict[str, Any]]:
    name = p.get("name") or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
    if not name:
        return None
    status = (p.get("email_status") or "").lower()
    email = p.get("email") if status in GOOD_STATUSES else None
    return {"name": name, "title": p.get("title") or p.get("headline"), "email": email, "email_status": status or None,
            "linkedin": p.get("linkedin_url"), "source": "apollo"}


def match(api_key: str, domain: str, name: Optional[str] = None, linkedin: Optional[str] = None,
          apollo_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    body: dict[str, Any] = {"domain": domain}
    if apollo_id:
        body["id"] = apollo_id
    if linkedin:
        body["linkedin_url"] = linkedin
    if name:
        parts = name.split()
        body["first_name"], body["last_name"] = parts[0], parts[-1] if len(parts) > 1 else ""
    try:
        data = _post(api_key, "people/match", body)
    except ApolloQuotaError:
        raise
    except ApolloError as e:
        logger.info("apollo match failed for %s @ %s: %s", name or linkedin or apollo_id, domain, e)
        return None
    person = data.get("person")
    return _person(person) if isinstance(person, dict) else None


def search_leaders(api_key: str, domain: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        data = _post(api_key, "mixed_people/api_search", {
            "q_organization_domains_list": [domain], "person_seniorities": LEADER_SENIORITIES, "per_page": limit,
        })
    except ApolloQuotaError:
        raise
    except ApolloError as e:
        logger.info("apollo search failed for %s: %s", domain, e)
        return []
    return [p for p in data.get("people") or [] if isinstance(p, dict) and p.get("id")]
