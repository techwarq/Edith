import json
import logging
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from edith.memory import job_applications_store as jobs_store
from edith.memory import startup_leads_store as leads_store
from edith.memory import store
from edith.startup_finder import apollo, crustdata, email_draft, prospeo, qualify, site_emails, sources

logger = logging.getLogger("edith.startup_finder")

LAST_CRAWL_KEY = "startup_finder_last_crawl"
CRAWL_TTL = timedelta(hours=6)
MAX_PER_COMPANY = 1

FALLBACK_PROFILE = (
    "Sonali Nayak, Bengaluru. Full-stack + AI engineer who builds agents that do real work. "
    "Built Clep (paste your site, describe the video, get a studio-grade launch video), "
    "nagent.ai UGC video agent, Campaign Hub, Virtual Photoshoot Agent, ai-lens (eval framework for "
    "text/image/video/audio AI apps, on PyPI), Edith (personal agent with memory, voice, Mac control). "
    "Python, TypeScript, Node, Cloudflare Workers/Queues/Durable Objects, GCP, Postgres, Redis."
)


def _hn_title(lead: dict[str, Any]) -> Optional[str]:
    best, best_pts = None, 0
    for part in lead.get("_parts") or []:
        for chunk in re.split(r",| and |;| – | - ", part):
            pts, _ = qualify.role_fit(chunk.strip())
            if pts > best_pts:
                best, best_pts = chunk.strip(), pts
    if best:
        return best
    for line in (lead.get("job_text") or "").split("\n")[:30]:
        line = line.strip(" -•*")
        if 4 < len(line) < 80:
            pts, _ = qualify.role_fit(line)
            if pts > best_pts:
                best, best_pts = line, pts
    return best


def _is_promising_company(lead: dict[str, Any]) -> bool:
    if lead.get("region") not in qualify.TARGET_REGIONS + qualify.UNRESOLVED_REGIONS:
        return False
    text = f"{lead.get('company', '')} {lead.get('description', '')} {' '.join(lead.get('tags') or [])}".lower()
    return bool(qualify._has_any(text, qualify.AI_TERMS))


def crawl(on_progress: Optional[Callable[[str], None]] = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tasks: dict[str, Callable[[], list[dict[str, Any]]]] = {}
    for fund, nid in sources.GETRO_FUNDS.items():
        tasks[f"{fund} jobs"] = lambda f=fund, n=nid: sources.getro_jobs(f, n)
        tasks[f"{fund} companies"] = lambda f=fund, n=nid: sources.getro_companies(f, n)
    for fund, (base, board) in sources.CONSIDER_FUNDS.items():
        tasks[f"{fund} jobs"] = lambda f=fund, b=base, i=board: sources.consider_jobs(f, b, i)
    tasks["a16z speedrun"] = lambda: sources.speedrun_companies(_is_promising_company)
    tasks["HN Who is Hiring"] = sources.hn_who_is_hiring
    for code, country in sources.HUB_COUNTRIES.items():
        tasks[f"The Hub {country}"] = lambda c=code, n=country: sources.thehub_companies(c, n)

    raw: list[dict[str, Any]] = []
    report: dict[str, Any] = {"sources": {}, "errors": {}}
    started = time.monotonic()
    with ThreadPoolExecutor(12) as ex:
        futures = {ex.submit(fn): name for name, fn in tasks.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                rows = fut.result()
                raw.extend(rows)
                report["sources"][name] = len(rows)
                if on_progress:
                    on_progress(f"{name}: {len(rows)}")
            except Exception as e:
                logger.warning("source %s failed: %s", name, e)
                report["errors"][name] = str(e)[:200]

    speedrun = [r for r in raw if r.get("source") == "speedrun"]
    if speedrun:
        with ThreadPoolExecutor(8) as ex:
            for rows in ex.map(lambda c: sources.ats_jobs(c["company"], c.get("domain"), c["fund"], c), speedrun):
                raw.extend(rows)

    report["crawl_seconds"] = round(time.monotonic() - started, 1)
    report["raw"] = len(raw)
    return raw, report


def qualify_all(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen: set[str] = set()
    for lead in raw:
        if not lead.get("company") or not lead.get("dedup_key"):
            continue
        if lead["dedup_key"] in seen:
            continue
        seen.add(lead["dedup_key"])
        if lead.get("source") == "hn":
            lead["role_title"] = _hn_title(lead)
            if not lead["role_title"]:
                continue
        scored = qualify.score(lead)
        if scored:
            out.append(scored)
    return out


def _crawl_is_fresh(conn: sqlite3.Connection) -> bool:
    last = store.get_meta(conn, LAST_CRAWL_KEY)
    if not last:
        return False
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(last) < CRAWL_TTL
    except ValueError:
        return False


PORTFOLIO_TTL = timedelta(days=7)
PORTFOLIO_CHUNK = 45_000


def _extract_portfolio(genai_client: Any, model: str, fund: str, text: str) -> list[dict[str, Any]]:
    companies: list[dict[str, Any]] = []
    for i in range(0, len(text), PORTFOLIO_CHUNK):
        chunk = text[i:i + PORTFOLIO_CHUNK]
        prompt = (
            f"Below is the text of the {fund} venture fund's portfolio page. Website domains appear in [brackets] "
            "next to the company they belong to. List EVERY portfolio company on it.\n"
            "Return JSON only: [{\"name\": str, \"domain\": str, \"about\": str, \"country\": str}]\n"
            "- domain: from the [brackets] next to that company, else \"\"\n"
            "- about: the company's own one-liner from the page, verbatim, max 25 words, else \"\"\n"
            "- country: only if the page states it, else \"\"\n"
            "Skip the fund itself, its team, news, and anything that is not a portfolio company.\n\n"
            f"{chunk}"
        )
        resp = genai_client.models.generate_content(model=model, contents=prompt)
        m = re.search(r"\[.*\]", resp.text or "", re.S)
        if not m:
            continue
        try:
            rows = json.loads(m.group(0))
        except ValueError:
            continue
        companies.extend(r for r in rows if isinstance(r, dict) and r.get("name"))
    return companies


def _portfolio_leads(fund: str, companies: list[dict[str, Any]], default_region: Optional[str]) -> list[dict[str, Any]]:
    leads = []
    for c in companies:
        domain = sources.domain_of(c.get("domain") or "")
        if not domain:
            continue
        country = (c.get("country") or "").strip()
        region = qualify.region_of(country) if country else (default_region or "other")
        if region in ("global", "apac") and default_region:
            region = default_region
        leads.append({
            "kind": "founder",
            "dedup_key": f"co:{domain}",
            "company": str(c["name"]).strip()[:80],
            "domain": domain,
            "company_url": f"https://{domain}",
            "fund": fund,
            "source": "portfolio",
            "locations": [country] if country else [],
            "region": region,
            "description": c.get("about") or "",
        })
    return leads


def portfolio_sources(conn: sqlite3.Connection, genai_client: Any, model: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report: dict[str, Any] = {"sources": {}, "errors": {}}
    now = datetime.now(timezone.utc)

    def one(item: tuple[str, tuple[str, Optional[str]]]) -> tuple[str, list[dict[str, Any]], Optional[str]]:
        fund, (url, default_region) = item
        key = f"startup_finder_portfolio:{fund}"
        cached = store.get_meta(conn, key)
        if cached:
            try:
                data = json.loads(cached)
                if now - datetime.fromisoformat(data["at"]) < PORTFOLIO_TTL:
                    return fund, _portfolio_leads(fund, data["companies"], default_region), None
            except (ValueError, KeyError):
                pass
        if genai_client is None:
            return fund, [], None
        try:
            companies = _extract_portfolio(genai_client, model, fund, sources.portfolio_page_text(url))
        except Exception as e:
            return fund, [], str(e)[:200]
        if companies:
            store.set_meta(conn, key, json.dumps({"at": now.isoformat(), "companies": companies}))
        return fund, _portfolio_leads(fund, companies, default_region), None

    leads: list[dict[str, Any]] = []
    with ThreadPoolExecutor(6) as ex:
        for fund, rows, err in ex.map(one, sources.PORTFOLIO_PAGES.items()):
            if err:
                report["errors"][f"{fund} portfolio"] = err
            else:
                report["sources"][f"{fund} portfolio"] = len(rows)
                leads.extend(rows)
    return leads, report


def refresh(
    conn: sqlite3.Connection,
    on_progress: Optional[Callable[[str], None]] = None,
    genai_client: Any = None,
    model: str = "",
) -> dict[str, Any]:
    raw, report = crawl(on_progress)
    portfolio, p_report = portfolio_sources(conn, genai_client, model)
    raw.extend(portfolio)
    report["sources"].update(p_report["sources"])
    report["errors"].update(p_report["errors"])
    report["raw"] = len(raw)
    qualified = qualify_all(raw)
    report["qualified"] = len(qualified)
    report["new"] = leads_store.upsert_leads(conn, qualified)
    if not report["errors"]:
        report["pruned"] = leads_store.prune_new(conn, {l["dedup_key"] for l in qualified})
    store.set_meta(conn, LAST_CRAWL_KEY, datetime.now(timezone.utc).isoformat())
    return report


def company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", email_draft.short_name(name or "").lower())


LOCATION_CURSOR_KEY = "startup_finder_crustdata_search:"
SEARCH_PAGES = 4


def crustdata_location_leads(
    conn: sqlite3.Connection, api_key: str, location: str, min_team: Optional[int], max_team: Optional[int], need: int,
) -> dict[str, Any]:
    known = leads_store.known_keys(conn)
    added, seen, cursor = 0, 0, None
    for _ in range(SEARCH_PAGES):
        try:
            rows, cursor = crustdata.search_companies(api_key, location, min_team, max_team, limit=50, cursor=cursor)
        except crustdata.CrustdataError as e:
            logger.warning("crustdata search failed for %s: %s", location, e)
            return {"added": added, "seen": seen, "error": str(e)[:200]}
        seen += len(rows)
        fresh = []
        for lead in rows:
            if lead["dedup_key"] in known:
                continue
            known.add(lead["dedup_key"])
            info = lead["company_info"]
            lead["region"] = qualify.region_of(info.get("hq"), info.get("country")) if info.get("hq") or info.get("country") else "other"
            lead["funded"], lead["funding"] = True, info.get("last_round") or ""
            if (scored := qualify.score(lead)) is not None:
                fresh.append(scored)
        added += leads_store.upsert_leads(conn, fresh)
        if added >= need or not cursor:
            break
    return {"added": added, "seen": seen}


def _select(
    conn: sqlite3.Connection,
    count: int,
    kind: Optional[str],
    exclude: Optional[set[int]] = None,
    taken: Optional[set[str]] = None,
    location: Optional[str] = None,
    max_team: Optional[int] = None,
    min_team: Optional[int] = None,
    allow_unknown_team: bool = False,
) -> list[dict[str, Any]]:
    skip_domains = leads_store.contacted_domains(conn)
    skip_names = {company_key(n) for n in leads_store.used_company_names(conn)}
    exclude = exclude or set()
    pool = leads_store.pick_new(
        conn, limit=count * 12 + len(exclude), kind=kind, location=location,
        max_team=max_team, min_team=min_team, allow_unknown_team=allow_unknown_team,
    )
    picked: list[dict[str, Any]] = []
    per_company: dict[str, int] = {k: MAX_PER_COMPANY for k in (taken or set())}
    for lead in pool:
        key = (lead.get("domain") or lead["company"]).lower()
        if lead["id"] in exclude:
            continue
        if lead.get("domain") and lead["domain"] in skip_domains:
            continue
        name_key = company_key(lead["company"])
        if name_key in skip_names:
            continue
        if per_company.get(key, 0) >= MAX_PER_COMPANY:
            continue
        if per_company.get(f"name:{name_key}", 0) >= MAX_PER_COMPANY:
            continue
        per_company[key] = per_company.get(key, 0) + 1
        per_company[f"name:{name_key}"] = per_company.get(f"name:{name_key}", 0) + 1
        picked.append(lead)
        if len(picked) >= count:
            break
    return picked


def _hunter_founders(api_key: str, lead: dict[str, Any]) -> tuple[list[dict[str, Any]], Optional[str]]:
    from edith.tools.growth.hunter import HunterError, _get

    params: dict[str, Any] = {"limit": 5, "seniority": "executive"}
    if lead.get("domain"):
        params["domain"] = lead["domain"]
    else:
        params["company"] = lead["company"]
    try:
        data = _get("domain-search", api_key, params)
    except HunterError as e:
        _note_hunter(e)
        logger.info("hunter lookup failed for %s: %s", lead["company"], e)
        return [], None
    people = []
    for e in data.get("emails") or []:
        name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x)
        people.append({"name": name or None, "title": e.get("position") or e.get("position_raw"), "email": e.get("value"), "linkedin": e.get("linkedin"), "confidence": e.get("confidence")})
    people.sort(key=lambda p: (_contact_rank(p.get("title")), -(p.get("confidence") or 0)))
    best = next((p["email"] for p in people if p.get("email")), None)
    return people[:3], best


FIT_THRESHOLD = 6
JUDGE_BATCH = 10


def _judge(genai_client: Any, model: str, profile: str, leads: list[dict[str, Any]]) -> dict[int, tuple[int, str, str, str, str]]:
    items = []
    for l in leads:
        facts = crustdata.format_info(l["company_info"]) if l.get("company_info") else ""
        if l["kind"] == "role":
            items.append({"id": l["id"], "type": "job", "company": l["company"], "title": l.get("role_title"),
                          "posting": (l.get("_jd") or l.get("description") or "")[:3500], "facts": facts})
        else:
            items.append({"id": l["id"], "type": "startup_no_open_role", "company": l["company"],
                          "about": (l.get("description") or "")[:1200], "facts": facts})
    prompt = (
        "You screen job leads for one candidate. Be strict: she only wants leads she can realistically win.\n\n"
        f"CANDIDATE RESUME:\n{profile[:3500]}\n\n"
        "Her real strengths: building LLM apps and multi-agent systems, RAG, full-stack TypeScript/Python/Node, "
        "backend infra (queues, Redis, Postgres, Cloudflare, GCP), creative-AI products (video/UGC/image agents), "
        "evals. About 2 years of professional experience, based in India, remote only.\n\n"
        "Score each lead 0-10 for fit:\n"
        "- job: does her actual experience cover the CORE requirements? Score <=3 if it needs classical ML/NLP model "
        "training, research, PhD, C/C++/Rust/Go as primary language, mobile/native, deep data engineering, 5+ years "
        "or staff-level seniority, a language other than English, on-site/relocation, or says candidates must live "
        "in a specific country/region that is not India. Score 7+ only if she could start shipping in week one.\n"
        "- startup_no_open_role: would a founder there plausibly want her as an engineer, given what they build?\n\n"
        "Also give hq: where the company is headquartered, from the posting or what you know about it — one of "
        "europe, middle_east, us, other, unknown. UK, Israel, Turkey and the Gulf count as europe/middle_east.\n"
        "And funded: has the company raised outside money (angels/VC/accelerator) — yes, no, or unknown.\n"
        "And ai: is AI/ML core to the company's product (not just a buzzword or an internal tool) — yes or no.\n\n"
        "Return JSON only: {\"<id>\": {\"fit\": <0-10>, \"hq\": \"<region>\", \"funded\": \"yes|no|unknown\", \"ai\": \"yes|no\", \"why\": \"<max 12 words, concrete>\"}}\n\n"
        f"{json.dumps(items)}"
    )
    try:
        resp = genai_client.models.generate_content(model=model, contents=prompt)
        m = re.search(r"\{.*\}", resp.text or "", re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        logger.warning("fit judge failed: %s", e)
        return {}
    out: dict[int, tuple[int, str, str, str, str]] = {}
    for k, v in data.items():
        if str(k).isdigit() and isinstance(v, dict):
            try:
                out[int(k)] = (
                    int(v.get("fit", 0)), str(v.get("why") or ""), str(v.get("hq") or "unknown").lower(),
                    str(v.get("funded") or "unknown").lower(), str(v.get("ai") or "yes").lower(),
                )
            except (TypeError, ValueError):
                continue
    return out


def _enrich_batch(conn: sqlite3.Connection, api_key: str, leads: list[dict[str, Any]]) -> None:
    todo = [l for l in leads if l.get("domain") and (
        not l.get("company_info") or (not l.get("founders") and not l["company_info"].get("people_checked")))]
    if not todo:
        return
    infos = crustdata.enrich(api_key, [l["domain"] for l in todo])
    _apply_crustdata(todo, infos)
    for lead in todo:
        if lead.get("company_info"):
            lead["company_info"]["people_checked"] = True
            leads_store.set_contacts(conn, lead["id"], lead.get("founders"), lead.get("contact_email"))
            leads_store.set_company_info(conn, lead["id"], lead["company_info"], lead.get("team_size"), lead.get("stage"))
            if lead.get("region"):
                leads_store.set_region(conn, lead["id"], lead["region"])


def _team_ok(lead: dict[str, Any], min_team: Optional[int], max_team: Optional[int]) -> bool:
    if not (min_team or max_team):
        return True
    size = (lead.get("company_info") or {}).get("headcount") or lead.get("team_size")
    if not size:
        return False
    return (min_team or 0) <= size <= (max_team or 10**9)


def _crust_funded(lead: dict[str, Any]) -> bool:
    info = lead.get("company_info") or {}
    return bool(info.get("total_funding_usd") or info.get("last_round") or info.get("investors"))


def _screen(
    conn: sqlite3.Connection,
    genai_client: Any,
    model: str,
    profile: str,
    count: int,
    kind: Optional[str],
    location: Optional[str] = None,
    max_team: Optional[int] = None,
    min_team: Optional[int] = None,
    require_ai: bool = True,
    crustdata_api_key: str = "",
) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    tried: set[int] = set()
    taken: set[str] = set()
    for _ in range(8):
        need = count - len(accepted)
        if need <= 0:
            break
        batch = _select(conn, need * 2, kind, exclude=tried, taken=taken, location=location,
                        max_team=max_team, min_team=min_team, allow_unknown_team=bool(crustdata_api_key))
        if not batch:
            break
        tried.update(l["id"] for l in batch)
        if crustdata_api_key:
            _enrich_batch(conn, crustdata_api_key, batch)
        sized = []
        for lead in batch:
            hq_known = bool((lead.get("company_info") or {}).get("hq"))
            if hq_known and lead.get("region") not in qualify.TARGET_REGIONS:
                leads_store.update_status(conn, lead["id"], "skipped")
            elif _team_ok(lead, min_team, max_team):
                sized.append(lead)
            else:
                leads_store.update_status(conn, lead["id"], "skipped")
        batch = sized
        if not batch:
            continue
        roles = [l for l in batch if l["kind"] == "role"]
        with ThreadPoolExecutor(8) as ex:
            for lead, text in zip(roles, ex.map(lambda l: sources.fetch_job_text(l.get("job_url")), roles)):
                lead["_jd"] = text
        chunks = [batch[i:i + JUDGE_BATCH] for i in range(0, len(batch), JUDGE_BATCH)]
        verdicts: dict[int, tuple[int, str, str, str, str]] = {}
        with ThreadPoolExecutor(4) as ex:
            for v in ex.map(lambda c: _judge(genai_client, model, profile, c), chunks):
                verdicts.update(v)
        for lead in batch:
            if lead["id"] not in verdicts:
                continue
            fit, why, hq, funded, ai = verdicts[lead["id"]]
            if lead.get("source") not in qualify.VC_SOURCES + ("thehub",) and funded != "yes" and not _crust_funded(lead):
                leads_store.update_status(conn, lead["id"], "skipped")
                continue
            if require_ai and ai == "no":
                leads_store.update_status(conn, lead["id"], "skipped")
                continue
            if lead.get("region") not in qualify.TARGET_REGIONS:
                if hq not in qualify.TARGET_REGIONS:
                    leads_store.update_status(conn, lead["id"], "skipped")
                    continue
                lead["region"] = hq
                leads_store.set_region(conn, lead["id"], hq)
            if fit < FIT_THRESHOLD:
                leads_store.update_status(conn, lead["id"], "skipped")
                continue
            key = (lead.get("domain") or lead["company"]).lower()
            name_key = f"name:{company_key(lead['company'])}"
            if key in taken or name_key in taken:
                continue
            taken.update((key, name_key))
            lead["fit"] = fit
            lead["reasons"] = [f"fit {fit}/10: {why}"] + [r for r in (lead.get("reasons") or []) if not r.startswith("fit ")]
            accepted.append(lead)
    accepted.sort(key=lambda l: (l["fit"], l["score"]), reverse=True)
    return accepted[:count]


def _contact_rank(title: Optional[str]) -> int:
    t = (title or "").lower()
    if "founder" in t:
        return 0
    if re.search(r"\b(ceo|cto|chief (executive|technology))\b", t):
        return 1
    if re.search(r"\b(head of (engineering|ai|product|talent)|vp (of )?engineering|engineering)\b", t):
        return 2
    if re.search(r"\b(talent|recruit|people)\b", t):
        return 3
    return 4


def _norm_linkedin(url: Optional[str]) -> str:
    return re.sub(r"^(https?://)?(www\.)?", "", (url or "").lower()).rstrip("/")


def _same_person(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("email") and a.get("email", "").lower() == (b.get("email") or "").lower():
        return True
    if a.get("linkedin") and _norm_linkedin(a["linkedin"]) == _norm_linkedin(b.get("linkedin")):
        return True
    na, nb = (a.get("name") or "").lower().split(), (b.get("name") or "").lower().split()
    if not na or not nb:
        return False
    if na == nb:
        return True
    same_last = len(na) > 1 and len(nb) > 1 and (na[-1].startswith(nb[-1].rstrip(".")) or nb[-1].startswith(na[-1].rstrip(".")))
    same_title = (a.get("title") or "").lower() == (b.get("title") or "").lower() and a.get("title")
    return na[0] == nb[0] and bool(same_last or same_title)


def _merge_people(known: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for p in [dict(x) for x in known] + [dict(x) for x in extra]:
        match = next((m for m in merged if _same_person(m, p)), None)
        if match is None:
            merged.append(p)
            continue
        if len(p.get("name") or "") > len(match.get("name") or ""):
            match["name"] = p["name"]
        for k, v in p.items():
            if v and not match.get(k):
                match[k] = v
    return merged


def _apply_crustdata(leads: list[dict[str, Any]], infos: dict[str, dict[str, Any]]) -> None:
    for lead in leads:
        info = infos.get((lead.get("domain") or "").lower())
        if not info:
            continue
        lead["company_info"] = {**(lead.get("company_info") or {}), **{k: v for k, v in info.items() if k != "founders"}}
        if info.get("founders"):
            lead["founders"] = _merge_people(lead.get("founders") or [], info["founders"])
        if info.get("headcount"):
            lead["team_size"] = info["headcount"]
        if info.get("last_round") and not lead.get("stage"):
            lead["stage"] = info["last_round"]
        hq_region = qualify.region_of(info.get("hq")) if info.get("hq") else None
        if hq_region and hq_region not in ("other", "global", "apac"):
            lead["region"] = hq_region
        if info.get("description") and len(info["description"]) > len(lead.get("description") or ""):
            lead["description"] = info["description"]


def _note_hunter(e: Exception) -> None:
    if re.search(r"\b(429|402|403)\b|limit|quota|plan", str(e), re.I):
        QUOTA_HIT.add("hunter")


NON_TECH = re.compile(r"\b(sales|marketing|finance|financial|legal|account|hr|people|recruit|talent|customer|partnership)", re.I)


def _hunter_email(api_key: str, domain: str, name: str) -> Optional[str]:
    from edith.tools.growth.hunter import HunterError, _get

    parts = name.split()
    if len(parts) < 2:
        return None
    try:
        data = _get("email-finder", api_key, {"domain": domain, "first_name": parts[0], "last_name": parts[-1]})
    except HunterError as e:
        _note_hunter(e)
        logger.info("hunter email-finder failed for %s @ %s: %s", name, domain, e)
        return None
    return data.get("email")


GENERIC_PREFERENCE = ("founders", "founder", "hello", "hi", "team", "contact", "info", "jobs", "careers")


def _hunter_generic(api_key: str, domain: str) -> Optional[str]:
    from edith.tools.growth.hunter import HunterError, _get

    try:
        data = _get("domain-search", api_key, {"domain": domain, "limit": 10, "type": "generic"})
    except HunterError as e:
        _note_hunter(e)
        logger.info("hunter generic lookup failed for %s: %s", domain, e)
        return None
    emails = [e.get("value") for e in data.get("emails") or [] if e.get("value")]
    rank = {p: i for i, p in enumerate(GENERIC_PREFERENCE)}
    emails.sort(key=lambda e: rank.get(e.split("@")[0].lower(), len(rank)))
    return emails[0] if emails else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _email_belongs(email: Optional[str], lead: dict[str, Any]) -> bool:
    if not email or "@" not in email:
        return False
    host = email.rsplit("@", 1)[1].lower()
    if lead.get("domain") and (host == lead["domain"].lower() or lead["domain"].lower().endswith("." + host)):
        return True
    core = _slug(host.split(".")[0])
    name = email_draft.short_name(lead.get("company") or "")
    brands = {_slug(name), _slug(name.split()[0]) if name.split() else ""} - {""}
    return any(len(b) >= 3 and (b in core or (len(core) >= 4 and core in b)) for b in brands)


def _apollo_contacts(api_key: str, lead: dict[str, Any], people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    domain = lead["domain"]
    named = [p for p in people if p.get("name") and email_draft.contact_rank(p.get("title")) < 4]
    if not named:
        leaders = [p for p in apollo.search_leaders(api_key, domain) if not NON_TECH.search(p.get("title") or "")]
        leaders.sort(key=lambda p: email_draft.contact_rank(p.get("title")))
        for hit in [p for p in leaders if p.get("has_email")][:2]:
            if (person := apollo.match(api_key, domain, apollo_id=hit["id"])) is not None:
                if not _email_belongs(person.get("email"), lead):
                    person["email"] = None
                people = _merge_people(people, [person])
        return people
    for person in named[:3]:
        if person.get("email"):
            continue
        found = apollo.match(api_key, domain, name=person["name"], linkedin=person.get("linkedin"))
        if found and _email_belongs(found.get("email"), lead):
            person["email"], person["email_status"] = found["email"], found.get("email_status")
            person["linkedin"] = person.get("linkedin") or found.get("linkedin")
    return people


def _prospeo_contacts(api_key: str, lead: dict[str, Any], people: list[dict[str, Any]]) -> None:
    named = [p for p in people if p.get("name") and email_draft.contact_rank(p.get("title")) < 4 and not p.get("email")]
    for person in named[:2]:
        found = prospeo.enrich(api_key, lead["domain"], name=person["name"], linkedin=person.get("linkedin"))
        if found and _email_belongs(found.get("email"), lead):
            person["email"], person["email_status"] = found["email"], found.get("email_status")
            person["linkedin"] = person.get("linkedin") or found.get("linkedin")


def _find_contacts(lead: dict[str, Any], hunter_api_key: str = "", apollo_api_key: str = "", prospeo_api_key: str = "") -> None:
    people = sorted(lead.get("founders") or [], key=lambda p: email_draft.contact_rank(p.get("title")))
    if apollo_api_key and lead.get("domain") and "apollo" not in QUOTA_HIT:
        try:
            people = _apollo_contacts(apollo_api_key, lead, people)
        except apollo.ApolloQuotaError:
            QUOTA_HIT.add("apollo")
        people.sort(key=lambda p: email_draft.contact_rank(p.get("title")))
    if prospeo_api_key and lead.get("domain") and "prospeo" not in QUOTA_HIT and not any(p.get("email") for p in people):
        try:
            _prospeo_contacts(prospeo_api_key, lead, people)
        except prospeo.ProspeoQuotaError:
            QUOTA_HIT.add("prospeo")
    if "hunter" in QUOTA_HIT:
        hunter_api_key = ""
    if hunter_api_key and lead.get("domain") and not any(p.get("email") for p in people):
        for person in [p for p in people if p.get("name") and email_draft.contact_rank(p.get("title")) < 4][:2]:
            if not person.get("email"):
                person["email"] = _hunter_email(hunter_api_key, lead["domain"], person["name"])
    lead["founders"] = people
    if hunter_api_key and not any(p.get("email") for p in people):
        found, email = _hunter_founders(hunter_api_key, lead)
        found = [p for p in found if not NON_TECH.search(p.get("title") or "")]
        email = email if any(p.get("email") == email for p in found) else next((p["email"] for p in found if p.get("email")), None)
        if found:
            lead["founders"] = _merge_people(people, found)
        lead["contact_email"] = lead.get("contact_email") or email
    if hunter_api_key and not any(p.get("email") for p in lead["founders"]) and not lead.get("contact_email") and lead.get("domain"):
        lead["contact_email"] = _hunter_generic(hunter_api_key, lead["domain"])
    if not any(p.get("email") for p in lead["founders"]) and not lead.get("contact_email") and lead.get("domain"):
        _site_contacts(lead)
    best = email_draft.pick_recipient(lead)
    if best and not lead.get("contact_email"):
        lead["contact_email"] = best["email"]


QUOTA_HIT: set[str] = set()


def _site_contacts(lead: dict[str, Any]) -> None:
    emails = site_emails.find(lead["domain"])
    if not emails:
        return
    people = lead.get("founders") or []
    firsts = [(p.get("name") or "").split()[0] for p in people if p.get("name")]
    email, first = site_emails.best(emails, firsts)
    if first:
        for p in people:
            if (p.get("name") or "").lower().startswith(first):
                p["email"], p["email_status"] = email, "on website"
                break
    else:
        lead["contact_email"] = email


def draft_for(lead: dict[str, Any], like: str, projects: str, focus: str = "") -> dict[str, Any]:
    draft = email_draft.compose(lead, like, projects, focus=focus)
    lead["draft_to"], lead["draft_subject"], lead["draft_body"] = draft["to"], draft["subject"], draft["body"]
    return draft


def find(
    conn: sqlite3.Connection,
    count: int = 10,
    kind: Optional[str] = None,
    force_refresh: bool = False,
    hunter_api_key: str = "",
    genai_client: Any = None,
    model: str = "",
    on_progress: Optional[Callable[[str], None]] = None,
    location: Optional[str] = None,
    max_team: Optional[int] = None,
    crustdata_api_key: str = "",
    min_team: Optional[int] = None,
    require_ai: bool = True,
    apollo_api_key: str = "",
    prospeo_api_key: str = "",
) -> dict[str, Any]:
    count = max(1, min(int(count), 50))
    report: dict[str, Any] = {}
    if force_refresh or not _crawl_is_fresh(conn) or leads_store.count_new(conn) < count * 2:
        report = refresh(conn, on_progress, genai_client, model)
    if location and crustdata_api_key:
        pool = len(leads_store.pick_new(conn, limit=count * 3, kind=kind, location=location, max_team=max_team,
                                        min_team=min_team, allow_unknown_team=True))
        if pool < count * 3:
            if on_progress:
                on_progress(f"Searching Crustdata for AI startups in {location}…")
            report["crustdata_search"] = crustdata_location_leads(
                conn, crustdata_api_key, location, min_team, max_team, need=count * 3 - pool)

    profile = jobs_store.get_resume_text(conn) or FALLBACK_PROFILE
    if genai_client is not None:
        if on_progress:
            on_progress("Checking size, funding and fit…")
        picked = _screen(conn, genai_client, model, profile, count, kind, location, max_team, min_team, require_ai, crustdata_api_key)
    else:
        picked = _select(conn, count, kind, location=location, max_team=max_team, min_team=min_team)
        if crustdata_api_key:
            _enrich_batch(conn, crustdata_api_key, picked)
    QUOTA_HIT.clear()
    if picked:
        if on_progress:
            on_progress("Finding founder and CTO emails…")
        with ThreadPoolExecutor(6) as ex:
            list(ex.map(lambda l: _find_contacts(l, hunter_api_key, apollo_api_key, prospeo_api_key), picked))

    parts = email_draft.personalize(genai_client, model, profile, picked)
    for lead in picked:
        like, projects, focus = parts.get(lead["id"], ("", "", ""))
        lead["pitch"] = f"i like that you're {like}" if like else None
        draft_for(lead, like, projects, focus)
        lead["status"] = "delivered"
        lead.pop("_jd", None)
        leads_store.mark_delivered(
            conn, lead["id"], founders=lead.get("founders"), contact_email=lead.get("contact_email"),
            pitch=lead.get("pitch"), reasons=lead.get("reasons"), company_info=lead.get("company_info"),
            team_size=lead.get("team_size"), stage=lead.get("stage"),
            draft_to=lead.get("draft_to"), draft_subject=lead.get("draft_subject"), draft_body=lead.get("draft_body"),
        )

    return {
        "requested": count,
        "returned": len(picked),
        "leads": picked,
        "remaining_pool": leads_store.count_new(conn),
        "crawl": report or None,
        "stats": leads_store.stats(conn),
        "warnings": quota_warnings(),
    }


def quota_warnings() -> list[str]:
    names = {"apollo": "Apollo is out of credits", "hunter": "Hunter is out of searches", "prospeo": "Prospeo is out of credits"}
    return [names[k] for k in sorted(QUOTA_HIT)]


def draft_lead(
    conn: sqlite3.Connection, lead_id: int, genai_client: Any, model: str,
    hunter_api_key: str = "", crustdata_api_key: str = "", apollo_api_key: str = "", prospeo_api_key: str = "",
) -> Optional[dict[str, Any]]:
    lead = leads_store.get_lead(conn, lead_id)
    if lead is None:
        return None
    if crustdata_api_key and lead.get("domain") and not lead.get("company_info"):
        _enrich_batch(conn, crustdata_api_key, [lead])
    QUOTA_HIT.clear()
    if email_draft.pick_recipient(lead) is None:
        _find_contacts(lead, hunter_api_key, apollo_api_key, prospeo_api_key)
    leads_store.set_contacts(conn, lead_id, lead.get("founders"), lead.get("contact_email"))
    profile = jobs_store.get_resume_text(conn) or FALLBACK_PROFILE
    like, projects, focus = email_draft.personalize(genai_client, model, profile, [lead]).get(lead_id, ("", "", ""))
    draft = draft_for(lead, like, projects, focus)
    leads_store.save_draft(conn, lead_id, draft["to"], draft["subject"], draft["body"])
    out = leads_store.get_lead(conn, lead_id)
    if out is not None:
        out["warnings"] = quota_warnings()
    return out
