import logging
import re
from typing import Any, Optional

import requests

logger = logging.getLogger("edith.startup_finder.crustdata")

BASE_URL = "https://api.crustdata.com"
API_VERSION = "2025-11-01"
BATCH = 25
TIMEOUT = 30
FIELDS = ["basic_info", "headcount", "funding", "locations", "hiring", "people", "social_profiles", "taxonomy"]


TECH_LEAD = re.compile(r"founder|\b(cto|ceo)\b|chief (technology|executive)|(head|vp|vice president|director) of (engineering|ai|technology)")


class CrustdataError(Exception):
    pass


def _post(api_key: str, path: str, body: dict[str, Any]) -> Any:
    try:
        resp = requests.post(
            f"{BASE_URL}{path}",
            json=body,
            headers={"authorization": f"Bearer {api_key}", "x-api-version": API_VERSION},
            timeout=TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        raise CrustdataError(f"network error calling Crustdata: {e}") from e
    if resp.status_code == 404:
        return []
    try:
        data = resp.json()
    except ValueError as e:
        raise CrustdataError(f"Crustdata returned non-JSON (status {resp.status_code})") from e
    if resp.status_code >= 400:
        err = data.get("error") if isinstance(data, dict) else None
        msg = err.get("message") if isinstance(err, dict) else resp.text[:200]
        raise CrustdataError(f"Crustdata API error ({resp.status_code}): {msg}")
    return data


def _person(p: dict[str, Any]) -> Optional[dict[str, Any]]:
    basic = p.get("basic_profile") or p.get("professional_network") or {}
    name = basic.get("name")
    if not name:
        return None
    handles = p.get("social_handles") or {}
    linkedin = ((handles.get("professional_network_identifier") or {}).get("profile_url"))
    return {"name": name, "title": basic.get("current_title") or basic.get("headline"), "linkedin": linkedin, "email": None}


def _summarize(data: dict[str, Any]) -> dict[str, Any]:
    basic = data.get("basic_info") or {}
    head = data.get("headcount") or {}
    fund = data.get("funding") or {}
    loc = data.get("locations") or {}
    hiring = data.get("hiring") or {}
    people = data.get("people") or {}
    social = data.get("social_profiles") or {}
    growth = head.get("growth_percent") or {}

    founders: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in ("founders", "cxos", "decision_makers"):
        for raw in people.get(group) or []:
            p = _person(raw) if isinstance(raw, dict) else None
            if p and group != "founders" and not TECH_LEAD.search((p["title"] or "").lower()):
                continue
            if p and p["name"].lower() not in seen:
                seen.add(p["name"].lower())
                founders.append(p)

    crunchbase = social.get("crunchbase")
    return {
        "name": basic.get("name"),
        "description": basic.get("description"),
        "year_founded": basic.get("year_founded"),
        "linkedin": basic.get("professional_network_url"),
        "crunchbase": crunchbase.get("url") if isinstance(crunchbase, dict) else None,
        "headcount": head.get("total"),
        "headcount_yoy_pct": growth.get("yoy"),
        "total_funding_usd": fund.get("total_investment_usd"),
        "last_round": fund.get("last_round_type"),
        "last_round_usd": fund.get("last_round_amount_usd"),
        "last_round_date": fund.get("last_fundraise_date"),
        "investors": (fund.get("investors") or [])[:8],
        "hq": loc.get("headquarters"),
        "country": loc.get("country"),
        "open_roles": hiring.get("openings_count"),
        "industry": (data.get("taxonomy") or {}).get("professional_network_industry"),
        "founders": founders[:4],
    }


def enrich(api_key: str, domains: list[str]) -> dict[str, dict[str, Any]]:
    domains = list(dict.fromkeys(d.lower() for d in domains if d))
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(domains), BATCH):
        chunk = domains[i:i + BATCH]
        try:
            rows = _post(api_key, "/company/enrich", {"domains": chunk, "fields": FIELDS, "exact_match": True})
        except CrustdataError as e:
            logger.warning("crustdata enrich failed for %d domains: %s", len(chunk), e)
            continue
        for row in rows if isinstance(rows, list) else []:
            matches = row.get("matches") or []
            if not matches:
                continue
            best = max(matches, key=lambda m: m.get("confidence_score") or 0)
            key = str(row.get("matched_on") or "").lower()
            if key and best.get("company_data"):
                out[key] = _summarize(best["company_data"])
    return out


def format_info(info: dict[str, Any]) -> str:
    bits = []
    if info.get("headcount"):
        size = f"{info['headcount']} people"
        if info.get("headcount_yoy_pct") is not None:
            size += f" ({info['headcount_yoy_pct']:+.0f}% yoy)"
        bits.append(size)
    if info.get("total_funding_usd"):
        money = f"${info['total_funding_usd'] / 1e6:.1f}M raised"
        if info.get("last_round") and info["last_round"] != "series_unknown":
            money += f", last {info['last_round'].replace('_', ' ')}"
            if info.get("last_round_date"):
                money += f" {info['last_round_date'][:7]}"
        bits.append(money)
    elif info.get("last_round") or info.get("investors"):
        round_ = (info.get("last_round") or "").replace("_", " ")
        bits.append("funded" + (f" ({round_})" if round_ and round_ != "series unknown" else "")
                    + (f" {info['last_round_date'][:7]}" if info.get("last_round_date") else ""))
    if info.get("hq"):
        bits.append(f"HQ {info['hq']}")
    if info.get("year_founded"):
        bits.append(f"founded {info['year_founded']}")
    if info.get("open_roles"):
        bits.append(f"{info['open_roles']} open roles")
    if info.get("investors"):
        bits.append("investors: " + ", ".join(info["investors"][:4]))
    return " · ".join(bits)


SEARCH_QUERY = "AI startup building AI products: generative AI, LLM apps, AI agents, machine learning"
SEARCH_FIELDS = [
    "basic_info.name", "basic_info.primary_domain", "basic_info.description", "basic_info.year_founded",
    "basic_info.professional_network_url", "headcount.total", "funding.total_investment_usd",
    "funding.last_round_type", "funding.last_fundraise_date", "funding.investors", "locations.headquarters",
    "locations.country",
]


def _location_condition(location: str) -> dict[str, Any]:
    locs = [l.strip() for l in location.split(",") if l.strip()]
    return {"op": "or", "conditions": [
        {"field": "locations.country", "type": "in", "value": locs},
        {"field": "locations.city", "type": "in", "value": locs},
    ]}


def search_companies(api_key: str, location: str, min_team: Optional[int], max_team: Optional[int],
                     limit: int = 50, cursor: Optional[str] = None) -> tuple[list[dict[str, Any]], Optional[str]]:
    conditions: list[dict[str, Any]] = [
        _location_condition(location),
        {"field": "funding.total_investment_usd", "type": ">", "value": 0},
    ]
    if min_team:
        conditions.append({"field": "headcount.total", "type": "=>", "value": min_team})
    if max_team:
        conditions.append({"field": "headcount.total", "type": "=<", "value": max_team})
    body: dict[str, Any] = {
        "search": {"query": SEARCH_QUERY, "mode": "hybrid"},
        "filters": {"op": "and", "conditions": conditions},
        "limit": limit,
        "fields": SEARCH_FIELDS,
    }
    if cursor:
        body["cursor"] = cursor
    data = _post(api_key, "/company/search", body)
    if not isinstance(data, dict):
        return [], None
    leads = []
    for c in data.get("companies") or []:
        basic = c.get("basic_info") or {}
        domain = (basic.get("primary_domain") or "").lower()
        if not domain or not basic.get("name"):
            continue
        info = _summarize(c)
        info.pop("founders", None)
        leads.append({
            "kind": "founder",
            "dedup_key": f"co:{domain}",
            "company": str(basic["name"]).strip()[:80],
            "domain": domain,
            "company_url": f"https://{domain}",
            "fund": "Crustdata",
            "source": "crustdata",
            "locations": [x for x in (info.get("hq"), (c.get("locations") or {}).get("country")) if x],
            "description": basic.get("description") or "",
            "team_size": info.get("headcount"),
            "stage": info.get("last_round"),
            "company_info": info,
        })
    return leads, data.get("next_cursor")
