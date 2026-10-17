from typing import Any, Callable, Literal, Optional

from edith.memory.records import career
from edith.startup_finder import crustdata, finder, llm
from edith.tools.base import ToolContext, tool


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


def _llm(ctx: ToolContext) -> tuple[Any, str]:
    if (router_llm := llm.from_settings(ctx.settings)) is not None:
        return router_llm, ctx.settings.startup_finder_model
    return ctx.genai_client, ctx.genai_model


@tool
def find_startups(
    ctx: ToolContext,
    count: int = 10,
    kind: Optional[Literal["role", "founder"]] = None,
    refresh: bool = False,
    location: str = "",
    max_team: int = 40,
    min_team: int = 10,
    on_progress: Optional[Callable[[str], None]] = None,
) -> str:
    """Find the user's next batch of target startups for her job search: VC/accelerator portfolio
    companies (a16z speedrun, Sequoia, Accel, Index, Antler, Techstars, Point Nine, Earlybird,
    Creandum, Cherry, Hub71 and more) plus HN Who is Hiring, filtered for remote roles open to
    someone in India at Europe/Middle East startups only (no US), creative-AI boosted. Returns exactly `count` new
    leads never shown before, each either a ROLE to apply to or a FOUNDER to cold-DM, with Crustdata company data
    (headcount, funding, HQ, investors), founder/CTO emails + LinkedIn, and a ready email draft she can send
    from the Eddy leads panel. Defaults to funded AI companies with 10-40 employees. Use whenever she asks for startups/leads/companies to reach out to.

    Args:
        count: How many leads she asked for (default 10, max 50).
        kind: 'role' = only open roles, 'founder' = only founder-DM targets. Omit for the best of both.
        refresh: Force a fresh crawl instead of using the last 6h of results.
        location: Only startups in these countries/cities, comma-separated, e.g. 'Norway' or 'Norway, Sweden, Denmark' or 'Berlin'.
        max_team: Max employees (default 40).
        min_team: Min employees (default 10).
    """
    if on_progress:
        on_progress("Searching VC portfolios for startups…")
    settings = ctx.settings
    genai_client, model = _llm(ctx)
    result = finder.find(
        ctx.conn,
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


@tool
def list_startup_leads(ctx: ToolContext, status: str = "delivered", kind: str = "", limit: int = 20) -> str:
    """List startup leads already found, filtered by status (new, delivered, contacted, applied, interview, rejected, skipped) and kind (role/founder)."""
    leads = career.list_leads(ctx.conn, status=status or None, kind=kind or None, limit=limit)
    if not leads:
        return "No startup leads with that filter."
    return "\n\n".join(format_lead(l) for l in leads)


@tool
def update_startup_lead(ctx: ToolContext, lead_id: int, status: Literal[tuple(career.LEAD_STATUSES)]) -> str:
    """Mark a startup lead as contacted, applied, interview, rejected or skipped."""
    try:
        ok = career.update_lead_status(ctx.conn, lead_id, status)
    except ValueError as e:
        return f"ERROR: {e}"
    return f"Lead #{lead_id} → {status}" if ok else f"ERROR: no lead #{lead_id}"
