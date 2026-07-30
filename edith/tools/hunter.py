"""Hunter.io integration — domain search / email finder / verifier / company
& person enrichment, for lead-gen and outreach workflows (finding real email
addresses to use with the existing send_email tool). All Hunter lookups here
are read-only (no side effects, no irreversible action), so — unlike
send_email/create_calendar_event — they're exposed directly rather than
gated through pending_actions/approve, same tier as gmail_search/web_search.
"""

from typing import Any, Optional

import requests

from edith.config import Settings
from edith.tools.registry import ToolRegistry

HUNTER_BASE_URL = "https://api.hunter.io/v2"
_TIMEOUT_SECONDS = 15


class HunterError(Exception):
    pass


def _get(endpoint: str, api_key: str, params: dict[str, Any]) -> dict[str, Any]:
    query = {k: v for k, v in params.items() if v not in (None, "")}
    query["api_key"] = api_key
    try:
        resp = requests.get(f"{HUNTER_BASE_URL}/{endpoint}", params=query, timeout=_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as e:
        raise HunterError(f"network error calling Hunter.io: {e}") from e

    try:
        body = resp.json()
    except ValueError as e:
        raise HunterError(f"Hunter.io returned a non-JSON response (status {resp.status_code})") from e

    if resp.status_code >= 400:
        errors = body.get("errors") or [{}]
        detail = errors[0].get("details") or errors[0].get("id") or resp.text
        raise HunterError(f"Hunter.io API error ({resp.status_code}): {detail}")

    return body.get("data") or {}


def register(registry: ToolRegistry, settings: Settings) -> None:
    api_key = settings.hunter_api_key

    def _require_key() -> Optional[str]:
        if not api_key:
            return "ERROR: Hunter.io isn't configured — HUNTER_API_KEY isn't set."
        return None

    def domain_search(domain: str, limit: int = 10) -> str:
        if (err := _require_key()) is not None:
            return err
        try:
            data = _get("domain-search", api_key, {"domain": domain, "limit": limit})
        except HunterError as e:
            return f"ERROR: {e}"
        org = data.get("organization") or domain
        emails = data.get("emails") or []
        if not emails:
            return f"No emails found for {org}."
        pattern = data.get("pattern") or "no known pattern"
        lines = [f"{org} (email pattern: {pattern}):"]
        for e in emails[:limit]:
            name = " ".join(filter(None, [e.get("first_name"), e.get("last_name")])) or "(name unknown)"
            position = e.get("position") or ""
            lines.append(
                f"- {e.get('value')} — {name}{', ' + position if position else ''} "
                f"(confidence {e.get('confidence')})"
            )
        return "\n".join(lines)

    def email_finder(domain: str, first_name: str, last_name: str) -> str:
        if (err := _require_key()) is not None:
            return err
        try:
            data = _get("email-finder", api_key, {"domain": domain, "first_name": first_name, "last_name": last_name})
        except HunterError as e:
            return f"ERROR: {e}"
        email = data.get("email")
        if not email:
            return f"No email found for {first_name} {last_name} at {domain}."
        return f"{email} (confidence {data.get('score')}, {len(data.get('sources') or [])} source(s))"

    def email_verifier(email: str) -> str:
        if (err := _require_key()) is not None:
            return err
        try:
            data = _get("email-verifier", api_key, {"email": email})
        except HunterError as e:
            return f"ERROR: {e}"
        return f"{email}: {data.get('status')} (score {data.get('score')}, result: {data.get('result')})"

    def company_enrichment(domain: str) -> str:
        if (err := _require_key()) is not None:
            return err
        try:
            data = _get("companies/find", api_key, {"domain": domain})
        except HunterError as e:
            return f"ERROR: {e}"
        name = data.get("name") or domain
        industry = (data.get("category") or {}).get("industry")
        employees = (data.get("metrics") or {}).get("employees")
        desc = data.get("description") or ""
        header = name + (f" — {industry}" if industry else "") + (f" · {employees} employees" if employees else "")
        return f"{header}\n{desc}".strip()

    def person_enrichment(email: str) -> str:
        if (err := _require_key()) is not None:
            return err
        try:
            data = _get("people/find", api_key, {"email": email})
        except HunterError as e:
            return f"ERROR: {e}"
        person = data.get("person") or {}
        name = (person.get("name") or {}).get("fullName") or email
        employment = person.get("employment") or {}
        role = employment.get("title")
        company = employment.get("name")
        return name + (f" — {role}" if role else "") + (f" at {company}" if company else "")

    def combined_enrichment(email: str) -> str:
        if (err := _require_key()) is not None:
            return err
        try:
            data = _get("combined/find", api_key, {"email": email})
        except HunterError as e:
            return f"ERROR: {e}"
        person = data.get("person") or {}
        company = data.get("company") or {}
        name = (person.get("name") or {}).get("fullName") or email
        role = (person.get("employment") or {}).get("title")
        company_name = company.get("name")
        return name + (f" — {role}" if role else "") + (f" at {company_name}" if company_name else "")

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "hunter_domain_search",
                "description": (
                    "Find email addresses associated with a company's domain (e.g. all known emails at "
                    "acme.com), plus the company's email naming pattern. Use this to find contacts at a "
                    "specific company for outreach."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "e.g. 'stripe.com'"},
                        "limit": {"type": "integer", "description": "Max emails to return (default 10)"},
                    },
                    "required": ["domain"],
                },
            },
        },
        domain_search,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "hunter_email_finder",
                "description": "Find a specific person's professional email address, given their name and company domain.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "Company domain, e.g. 'stripe.com'"},
                        "first_name": {"type": "string"},
                        "last_name": {"type": "string"},
                    },
                    "required": ["domain", "first_name", "last_name"],
                },
            },
        },
        email_finder,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "hunter_email_verifier",
                "description": "Check whether an email address is deliverable before sending to it (catches typos/dead addresses).",
                "parameters": {
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                    "required": ["email"],
                },
            },
        },
        email_verifier,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "hunter_company_enrichment",
                "description": "Look up firmographic details (industry, size, description) for a company by its domain.",
                "parameters": {
                    "type": "object",
                    "properties": {"domain": {"type": "string"}},
                    "required": ["domain"],
                },
            },
        },
        company_enrichment,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "hunter_person_enrichment",
                "description": "Look up a person's name, role, and employer from their email address.",
                "parameters": {
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                    "required": ["email"],
                },
            },
        },
        person_enrichment,
    )

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "hunter_combined_enrichment",
                "description": "Look up both the person and their company from an email address in one call.",
                "parameters": {
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                    "required": ["email"],
                },
            },
        },
        combined_enrichment,
    )
