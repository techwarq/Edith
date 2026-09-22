"""Brand lead-generation agent — single file.

Takes a brand brief as input, uses TOOLS + an LLM to find, enrich,
score, and save leads.

  python agent.py --brand "Acme Coffee" --product "cold brew cans" \\
      --customer "cafes and offices in Bengaluru" --count 10

Or interactive (no flags):
  python agent.py

Needs:
  pip install openai requests python-dotenv
  OPENROUTER_API_KEY=... in env / .env   (or OPENAI_API_KEY)
Optional:
  HUNTER_API_KEY=... for real email lookup/enrichment

Flow:
  1. read BrandBrief (flags or input() prompts)
  2. LLM plans search queries -> web_search tool
  3. LLM extracts candidate leads from search output
  4. hunter/email tools enrich + verify (graceful if no key)
  5. LLM scores each lead + writes a personalised outreach angle
  6. save_leads tool writes leads_{brand}.csv + .json, prints table
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = os.environ.get("EDITH_MODEL", "qwen/qwen3.7-flash").strip() or "qwen/qwen3.7-flash"
MAX_TOOL_ITERATIONS = 8


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class BrandBrief:
    brand: str
    product: str
    customer: str
    region: str = "India"
    goal: str = "find resellers / B2B buyers"
    count: int = 10


@dataclass
class Lead:
    company: str
    contact: str = ""
    email: str = ""
    domain: str = ""
    why_fit: str = ""
    score: int = 0  # 0-100
    outreach_angle: str = ""
    source: str = ""

    def to_row(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# LLM client (OpenAI-compatible: OpenRouter default, OpenAI fallback)
# ---------------------------------------------------------------------------

def make_llm_client():
    try:
        import openai
    except ImportError:
        sys.exit("ERROR: pip install openai requests python-dotenv")

    key = os.environ.get("OPENROUTER_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        sys.exit("ERROR: set OPENROUTER_API_KEY (or OPENAI_API_KEY) in env / .env")
    base_url = OPENROUTER_BASE_URL if os.environ.get("OPENROUTER_API_KEY") else "https://api.openai.com/v1"
    model = DEFAULT_MODEL
    if base_url == "https://api.openai.com/v1" and "/" in model:
        model = "gpt-4o-mini"  # OpenRouter-style id won't exist on OpenAI
    return openai.OpenAI(base_url=base_url, api_key=key), model


# ---------------------------------------------------------------------------
# Tools (pure functions returning strings — the LLM calls these)
# ---------------------------------------------------------------------------

def tool_web_search(query: str, max_results: int = 5) -> str:
    """Free web search via DuckDuckGo instant-answer + html fallback. No key needed."""
    query = (query or "").strip()
    if not query:
        return "ERROR: query is required."
    try:
        # 1) instant answer API (fast, no scraping)
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=15,
            headers={"User-Agent": "leadgen-agent/1.0"},
        )
        data = r.json() if r.ok else {}
        lines: list[str] = []
        for item in (data.get("RelatedTopics") or [])[:max_results]:
            text = item.get("Text", "") if isinstance(item, dict) else ""
            url = item.get("FirstURL", "") if isinstance(item, dict) else ""
            if text:
                lines.append(f"- {text} ({url})" if url else f"- {text}")
        abstract = data.get("AbstractText") or ""
        if abstract:
            lines.insert(0, f"Summary: {abstract} [{data.get('AbstractURL', '')}]")
        if lines:
            return "\n".join(lines[: max_results + 1])
        # 2) fallback: html search scrape
        r2 = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (leadgen-agent)"},
        )
        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', r2.text or "")
        clean = [re.sub(r"<[^>]+>", "", t).strip() for t in titles][:max_results]
        clean = [t for t in clean if t]
        return "\n".join(f"- {t}" for t in clean) if clean else f"No results for '{query}'."
    except Exception as e:  # never crash the agent loop
        return f"ERROR: web search failed: {e}"


def tool_hunter_lookup(domain: str) -> str:
    """Company email pattern + a few public emails via Hunter.io (needs HUNTER_API_KEY)."""
    domain = (domain or "").strip().lower()
    if not domain:
        return "ERROR: domain is required (e.g. 'acme.com')."
    api_key = os.environ.get("HUNTER_API_KEY", "").strip()
    if not api_key:
        return "Hunter.io not configured (HUNTER_API_KEY unset) — skip email enrichment for this lead."
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "limit": 5, "api_key": api_key},
            timeout=15,
        )
        body = resp.json()
        if resp.status_code >= 400:
            err = (body.get("errors") or [{}])[0].get("details", resp.text)
            return f"ERROR: Hunter.io ({resp.status_code}): {err}"
        data = body.get("data") or {}
        emails = data.get("emails") or []
        pattern = data.get("pattern") or "unknown pattern"
        if not emails:
            return f"No public emails found for {domain} (pattern: {pattern})."
        out = [f"{domain} (pattern: {pattern}):"]
        for e in emails:
            name = " ".join(filter(None, [e.get("first_name"), e.get("last_name")])) or "unknown"
            out.append(f"- {e.get('value')} — {name} ({e.get('position') or 'no title'}, conf {e.get('confidence')})")
        return "\n".join(out)
    except Exception as e:
        return f"ERROR: Hunter.io lookup failed: {e}"


def tool_verify_email(email: str) -> str:
    """Cheap local sanity check (format + common typo domains). Not deliverability."""
    email = (email or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return f"{email}: INVALID format."
    domain = email.split("@")[1].lower()
    typos = {"gmial.com": "gmail.com", "gamil.com": "gmail.com", "hotmial.com": "hotmail.com",
             "yaho.com": "yahoo.com", "outlok.com": "outlook.com"}
    if domain in typos:
        return f"{email}: LIKELY TYPO — did you mean {email.split('@')[0]}@{typos[domain]}?"
    return f"{email}: format OK (deliverability not checked — use Hunter verifier for that)."


_SAVED_LEADS: list[dict] = []  # staging area the LLM fills via save_leads


def tool_save_leads(leads_json: str) -> str:
    """Stage verified leads for CSV/JSON export. Expects a JSON array of lead objects."""
    try:
        leads = json.loads(leads_json)
    except json.JSONDecodeError as e:
        return f"ERROR: leads_json is not valid JSON: {e}"
    if not isinstance(leads, list) or not leads:
        return "ERROR: leads_json must be a non-empty JSON array."
    added = 0
    for item in leads:
        if not isinstance(item, dict) or not item.get("company"):
            continue
        _SAVED_LEADS.append({
            "company": str(item.get("company", ""))[:120],
            "contact": str(item.get("contact", ""))[:120],
            "email": str(item.get("email", ""))[:120],
            "domain": str(item.get("domain", ""))[:120],
            "why_fit": str(item.get("why_fit", ""))[:500],
            "score": int(item.get("score", 0) or 0),
            "outreach_angle": str(item.get("outreach_angle", ""))[:500],
            "source": str(item.get("source", "llm+web_search"))[:120],
        })
        added += 1
    return f"Staged {added} lead(s) (total staged: {len(_SAVED_LEADS)})."


TOOLS: list[dict] = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the live web for candidate buyers/partners/distributors. Use specific queries like 'specialty coffee distributors Bengaluru'.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "description": "default 5"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "hunter_lookup",
        "description": "Look up public emails + email pattern for a company domain. Skip if domain unknown.",
        "parameters": {"type": "object", "properties": {
            "domain": {"type": "string", "description": "e.g. 'acme.com'"}}, "required": ["domain"]}}},
    {"type": "function", "function": {
        "name": "verify_email",
        "description": "Local format/typo check for an email address.",
        "parameters": {"type": "object", "properties": {
            "email": {"type": "string"}}, "required": ["email"]}}},
    {"type": "function", "function": {
        "name": "save_leads",
        "description": "Stage the final deduplicated, scored leads for export. Call once at the end with the full JSON array.",
        "parameters": {"type": "object", "properties": {
            "leads_json": {"type": "string", "description": "JSON array of {company, contact, email, domain, why_fit, score 0-100, outreach_angle, source}"}},
         "required": ["leads_json"]}}},
]


def dispatch_tool(name: str, args: dict) -> str:
    try:
        if name == "web_search":
            return tool_web_search(args.get("query", ""), int(args.get("max_results", 5) or 5))
        if name == "hunter_lookup":
            return tool_hunter_lookup(args.get("domain", ""))
        if name == "verify_email":
            return tool_verify_email(args.get("email", ""))
        if name == "save_leads":
            return tool_save_leads(args.get("leads_json", "[]"))
        return f"ERROR: unknown tool '{name}'"
    except Exception as e:
        return f"ERROR executing '{name}': {e}"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a B2B lead-generation agent for brands.
Given the brand brief in the first user message:
1. Plan 3-6 specific web_search queries (buyers, distributors, resellers, partners — include the region).
2. Call web_search for each (you can batch independent calls in one turn).
3. Extract real candidate companies from results — dedupe, drop irrelevant ones.
4. If a company domain is known, optionally call hunter_lookup and verify_email.
5. Score each lead 0-100 on fit (need + budget + region match) and write a 1-line personalised outreach_angle tied to the brand's product.
6. Call save_leads ONCE with the final JSON array (max = requested count), then give a short markdown table summary.
Never invent emails — only save emails returned by tools or clearly from search results. If unsure, leave email blank."""


class LeadGenAgent:
    """Input (BrandBrief) -> tool-using LLM loop -> list[Lead] + CSV/JSON files."""

    def __init__(self, client, model: str, verbose: bool = True) -> None:
        self.client = client
        self.model = model
        self.verbose = verbose

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, flush=True)

    def run(self, brief: BrandBrief) -> list[Lead]:
        _SAVED_LEADS.clear()
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content":
                f"Brand: {brief.brand}\nProduct/service: {brief.product}\n"
                f"Ideal customer: {brief.customer}\nRegion: {brief.region}\n"
                f"Goal: {brief.goal}\nMax leads: {brief.count}\n\n"
                f"Find, score, and save up to {brief.count} leads."},
        ]
        final_text = ""
        for _ in range(MAX_TOOL_ITERATIONS):
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=TOOLS, max_tokens=4096)
            msg = resp.choices[0].message
            assistant_msg: dict = {"role": "assistant", "content": msg.content or ""}
            tool_calls = msg.tool_calls or []
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls]
            messages.append(assistant_msg)
            if not tool_calls:
                final_text = msg.content or ""
                break
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                self._log(f"  [tool] {tc.function.name} {json.dumps(args)[:120]}")
                result = dispatch_tool(tc.function.name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:
            # cap hit — force summary without more tools
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages + [{"role": "user", "content": "Tool budget used up — summarise what you have, no more tool calls."}],
                max_tokens=2048)
            final_text = resp.choices[0].message.content or ""

        leads = [Lead(**d) for d in _SAVED_LEADS[: brief.count]]
        self._export(brief, leads)
        self._log("\n" + (final_text or "Done."))
        return leads

    def _export(self, brief: BrandBrief, leads: list[Lead]) -> None:
        slug = re.sub(r"[^a-z0-9]+", "_", brief.brand.lower()).strip("_") or "brand"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        csv_path = Path(f"leads_{slug}_{stamp}.csv")
        json_path = Path(f"leads_{slug}_{stamp}.json")
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["company", "contact", "email", "domain", "why_fit", "score", "outreach_angle", "source"])
            w.writeheader()
            for lead in sorted(leads, key=lambda l: l.score, reverse=True):
                w.writerow(lead.to_row())
        json_path.write_text(json.dumps(
            {"brand": brief.brand, "generated_at": stamp, "leads": [l.to_row() for l in leads]},
            indent=2, ensure_ascii=False), encoding="utf-8")
        self._log(f"\nSaved {len(leads)} leads -> {csv_path} + {json_path}")


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def read_brief(args: argparse.Namespace) -> BrandBrief:
    def ask(flag: str | None, prompt: str, default: str = "") -> str:
        if flag:
            return flag
        suffix = f" [{default}]" if default else ""
        try:
            val = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            val = ""
        return val or default

    return BrandBrief(
        brand=ask(args.brand, "Brand name"),
        product=ask(args.product, "Product/service"),
        customer=ask(args.customer, "Ideal customer (who should buy?)"),
        region=ask(args.region, "Region", "India"),
        goal=ask(args.goal, "Goal", "find resellers / B2B buyers"),
        count=args.count,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Lead-gen agent: brand in, scored leads out.")
    p.add_argument("--brand", default=None)
    p.add_argument("--product", default=None)
    p.add_argument("--customer", default=None)
    p.add_argument("--region", default=None)
    p.add_argument("--goal", default=None)
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    brief = read_brief(args)
    if not brief.brand or not brief.product or not brief.customer:
        sys.exit("ERROR: brand, product, and customer are required.")

    client, model = make_llm_client()
    print(f"Finding up to {brief.count} leads for '{brief.brand}' with {model} ...")
    agent = LeadGenAgent(client, model, verbose=not args.quiet)
    leads = agent.run(brief)
    print(f"\nDone: {len(leads)} leads for {brief.brand}.")
    for lead in sorted(leads, key=lambda l: l.score, reverse=True):
        print(f"  {lead.score:3d}  {lead.company} — {lead.contact or '?'} {lead.email or '(no email)'}")


if __name__ == "__main__":
    main()
