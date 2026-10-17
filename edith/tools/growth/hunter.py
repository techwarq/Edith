"""Hunter.io integration — domain search / email finder / verifier / company
& person enrichment, for lead-gen and outreach workflows (finding real email
addresses to use with the existing send_email tool). All Hunter lookups here
are read-only (no side effects, no irreversible action), so — unlike
send_email/create_calendar_event — they're exposed directly rather than
gated through pending_actions/approve, same tier as gmail_search/web_search.
"""

from typing import Any, Optional

import requests

from edith.tools.base import ToolContext, tool

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


def _lookup(ctx: ToolContext, endpoint: str, params: dict[str, Any]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    api_key = ctx.settings.hunter_api_key
    if not api_key:
        return None, "ERROR: Hunter.io isn't configured — HUNTER_API_KEY isn't set."
    try:
        return _get(endpoint, api_key, params), None
    except HunterError as e:
        return None, f"ERROR: {e}"


@tool
def hunter_domain_search(ctx: ToolContext, domain: str, limit: int = 10) -> str:
    """Find email addresses associated with a company's domain (e.g. all known emails at
    acme.com), plus the company's email naming pattern. Use this to find contacts at a
    specific company for outreach.

    Args:
        domain: e.g. 'stripe.com'
        limit: Max emails to return (default 10)
    """
    data, err = _lookup(ctx, "domain-search", {"domain": domain, "limit": limit})
    if err:
        return err
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


@tool
def hunter_email_finder(ctx: ToolContext, domain: str, first_name: str, last_name: str) -> str:
    """Find a specific person's professional email address, given their name and company domain.

    Args:
        domain: Company domain, e.g. 'stripe.com'
    """
    data, err = _lookup(ctx, "email-finder", {"domain": domain, "first_name": first_name, "last_name": last_name})
    if err:
        return err
    email = data.get("email")
    if not email:
        return f"No email found for {first_name} {last_name} at {domain}."
    return f"{email} (confidence {data.get('score')}, {len(data.get('sources') or [])} source(s))"


@tool
def hunter_email_verifier(ctx: ToolContext, email: str) -> str:
    """Check whether an email address is deliverable before sending to it (catches typos/dead addresses)."""
    data, err = _lookup(ctx, "email-verifier", {"email": email})
    if err:
        return err
    return f"{email}: {data.get('status')} (score {data.get('score')}, result: {data.get('result')})"


@tool
def hunter_company_enrichment(ctx: ToolContext, domain: str) -> str:
    """Look up firmographic details (industry, size, description) for a company by its domain."""
    data, err = _lookup(ctx, "companies/find", {"domain": domain})
    if err:
        return err
    name = data.get("name") or domain
    industry = (data.get("category") or {}).get("industry")
    employees = (data.get("metrics") or {}).get("employees")
    desc = data.get("description") or ""
    header = name + (f" — {industry}" if industry else "") + (f" · {employees} employees" if employees else "")
    return f"{header}\n{desc}".strip()


@tool
def hunter_person_enrichment(ctx: ToolContext, email: str) -> str:
    """Look up a person's name, role, and employer from their email address."""
    data, err = _lookup(ctx, "people/find", {"email": email})
    if err:
        return err
    person = data.get("person") or {}
    name = (person.get("name") or {}).get("fullName") or email
    employment = person.get("employment") or {}
    role = employment.get("title")
    company = employment.get("name")
    return name + (f" — {role}" if role else "") + (f" at {company}" if company else "")


@tool
def hunter_combined_enrichment(ctx: ToolContext, email: str) -> str:
    """Look up both the person and their company from an email address in one call."""
    data, err = _lookup(ctx, "combined/find", {"email": email})
    if err:
        return err
    person = data.get("person") or {}
    company = data.get("company") or {}
    name = (person.get("name") or {}).get("fullName") or email
    role = (person.get("employment") or {}).get("title")
    company_name = company.get("name")
    return name + (f" — {role}" if role else "") + (f" at {company_name}" if company_name else "")
