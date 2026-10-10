import sqlite3
from typing import Any, Callable, Optional

from edith.config import Settings
from edith.memory import startup_leads_store as leads_store
from edith.startup_finder import crustdata, finder, llm
from edith.tools.registry import ToolRegistry


def format_lead(lead: dict[str, Any]) -> str:
    head = f"#{lead['id']} {lead['company']}"
    if lead.get("domain"):
        head += f" ({lead['domain']})"
    head += f" — score {lead['score']:.0f}, via {lead.get('fund')}"
    lines = [head]
    if lead["kind"] == "role":
        lines.append(f"  ROLE: {lead.get('role_title')} [{lead.get('eligibility')}] {lead.get('job_url') or ''}")
        if lead.get("salary"):
            lines.append(f"  pay: {lead['salary']}")
    else:
        lines.append("  FOUNDER DM: no matching open role — reach out to the founder")
    if lead.get("company_info") and (facts := crustdata.format_info(lead["company_info"])):
        lines.append(f"  company: {facts}")
    if lead.get("reasons"):
        lines.append(f"  why: {', '.join(lead['reasons'][:5])}")
    for f in (lead.get("founders") or [])[:3]:
        bits = [f.get("name") or "?", f.get("title") or "", f.get("email") or "", f.get("linkedin") or ""]
        lines.append("  contact: " + " · ".join(b for b in bits if b))
    if lead.get("contact_email") and not any(f.get("email") == lead["contact_email"] for f in lead.get("founders") or []):
        lines.append(f"  email: {lead['contact_email']}")
    if lead.get("pitch"):
        lines.append(f"  hook: {lead['pitch']}")
    return "\n".join(lines)


def register(registry: ToolRegistry, conn: sqlite3.Connection, settings: Settings, genai_client: Any, model: str) -> None:
    if (router_llm := llm.from_settings(settings)) is not None:
        genai_client, model = router_llm, settings.startup_finder_model
    def find_startups(
        count: int = 10,
        kind: str = "",
        refresh: bool = False,
        location: str = "",
        max_team: int = 40,
        min_team: int = 10,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> str:
        if on_progress:
            on_progress("Searching VC portfolios for startups…")
        result = finder.find(
            conn,
            count=count,
            kind=kind or None,
            force_refresh=refresh,
            hunter_api_key=settings.hunter_api_key,
            genai_client=genai_client,
            model=model,
            on_progress=on_progress,
            location=location or None,
            max_team=max_team or None,
            min_team=(min_team if (max_team or 40) >= min_team else 1) or None,
            crustdata_api_key=settings.crustdata_api_key,
            apollo_api_key=settings.apollo_api_key,
            prospeo_api_key=settings.prospeo_api_key,
        )
        if not result["leads"]:
            return "No new startup leads matched right now. Try refresh=true or a different kind."
        header = f"{result['returned']} new startup leads ({result['remaining_pool']} more in the pool):"
        return header + "\n\n" + "\n\n".join(format_lead(l) for l in result["leads"])

    def list_startup_leads(status: str = "delivered", kind: str = "", limit: int = 20) -> str:
        leads = leads_store.list_leads(conn, status=status or None, kind=kind or None, limit=limit)
        if not leads:
            return "No startup leads with that filter."
        return "\n\n".join(format_lead(l) for l in leads)

    def update_startup_lead(lead_id: int, status: str) -> str:
        try:
            ok = leads_store.update_status(conn, lead_id, status)
        except ValueError as e:
            return f"ERROR: {e}"
        return f"Lead #{lead_id} → {status}" if ok else f"ERROR: no lead #{lead_id}"

    registry.register(
        {
            "type": "function",
            "function": {
                "name": "find_startups",
                "description": (
                    "Find the user's next batch of target startups for her job search: VC/accelerator portfolio "
                    "companies (a16z speedrun, Sequoia, Accel, Index, Antler, Techstars, Point Nine, Earlybird, "
                    "Creandum, Cherry, Hub71 and more) plus HN Who is Hiring, filtered for remote roles open to "
                    "someone in India at Europe/Middle East startups only (no US), creative-AI boosted. Returns exactly `count` new "
                    "leads never shown before, each either a ROLE to apply to or a FOUNDER to cold-DM, with Crustdata company data "
                    "(headcount, funding, HQ, investors), founder/CTO emails + LinkedIn, and a ready email draft she can send "
                    "from the Eddy leads panel. Defaults to funded AI companies with 10-40 employees. Use whenever she asks for startups/leads/companies to reach out to."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "How many leads she asked for (default 10, max 50)."},
                        "kind": {"type": "string", "enum": ["role", "founder"], "description": "'role' = only open roles, 'founder' = only founder-DM targets. Omit for the best of both."},
                        "refresh": {"type": "boolean", "description": "Force a fresh crawl instead of using the last 6h of results."},
                        "location": {"type": "string", "description": "Only startups in these countries/cities, comma-separated, e.g. 'Norway' or 'Norway, Sweden, Denmark' or 'Berlin'."},
                        "max_team": {"type": "integer", "description": "Max employees (default 40)."},
                        "min_team": {"type": "integer", "description": "Min employees (default 10)."},
                    },
                },
            },
        },
        find_startups,
    )
    registry.register(
        {
            "type": "function",
            "function": {
                "name": "list_startup_leads",
                "description": "List startup leads already found, filtered by status (new, delivered, contacted, applied, interview, rejected, skipped) and kind (role/founder).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "kind": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                },
            },
        },
        list_startup_leads,
    )
    registry.register(
        {
            "type": "function",
            "function": {
                "name": "update_startup_lead",
                "description": "Mark a startup lead as contacted, applied, interview, rejected or skipped.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"type": "integer"},
                        "status": {"type": "string", "enum": list(leads_store.STATUSES)},
                    },
                    "required": ["lead_id", "status"],
                },
            },
        },
        update_startup_lead,
    )
