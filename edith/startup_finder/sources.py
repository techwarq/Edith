import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests

from edith.startup_finder.qualify import region_of, team_size

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TIMEOUT = 20

GETRO_FUNDS = {
    "Antler": 7715,
    "Accel": 8672,
    "General Catalyst": 222,
    "Techstars": 89,
    "Point Nine": 1680,
    "Earlybird": 617,
    "Hub71": 9266,
    "Index Ventures": 1629,
    "Creandum": 53552,
    "Cherry Ventures": 44081,
    "Atomico": 36986,
    "Speedinvest": 947,
    "HV Capital": 234,
    "Dawn Capital": 3063,
    "Octopus Ventures": 4580,
    "MMC Ventures": 2303,
    "MEVP": 1034,
}
CONSIDER_FUNDS = {
    "Sequoia": ("https://jobs.sequoiacap.com", "sequoia-capital"),
    "Lightspeed": ("https://jobs.lsvp.com", "lightspeed"),
    "Notion Capital": ("https://jobs.notion.vc", "notion-capital"),
    "Kleiner Perkins": ("https://jobs.kleinerperkins.com", "kleiner-perkins"),
    "Bessemer": ("https://jobs.bvp.com", "bessemer-ventures"),
    "GV": ("https://jobs.gv.com", "gv"),
    "Felicis": ("https://jobs.felicis.com", "felicis"),
    "CRV": ("https://jobs.crv.com", "crv"),
    "Initialized": ("https://jobs.initialized.com", "initialized"),
    "LocalGlobe": ("https://jobs.phoenixcourt.vc", "localglobe-all"),
    "Balderton": ("https://careers.balderton.com", "balderton-capital"),
    "Hoxton Ventures": ("https://jobs.hoxtonventures.com", "hoxton-ventures"),
}
PORTFOLIO_PAGES = {
    "Seedcamp": ("https://seedcamp.com/our-companies/", None),
    "Kima Ventures": ("https://www.kimaventures.com/portfolio", None),
    "Picus Capital": ("https://picuscap.com/portfolio", None),
    "Project A": ("https://www.project-a.vc/portfolio", None),
    "Hummingbird": ("https://www.hummingbird.vc/portfolio", None),
    "Mosaic Ventures": ("https://www.mosaicventures.com/portfolio", None),
    "byFounders": ("https://byfounders.vc/portfolio", None),
    "Concept Ventures": ("https://concept.vc/portfolio", None),
    "Daphni": ("https://www.daphni.com/portfolio", None),
    "Elaia": ("https://www.elaia.com/portfolio", None),
    "Entrepreneur First": ("https://www.joinef.com/portfolio/", None),
    "Northzone": ("https://northzone.com/portfolio", None),
    "Partech": ("https://partechpartners.com/companies", None),
    "Redalpine": ("https://www.redalpine.com/portfolio", None),
    "VentureSouq": ("https://www.venturesouq.com/portfolio", "middle_east"),
    "Shorooq": ("https://www.shorooq.com/portfolio", "middle_east"),
    "Raed Ventures": ("https://raed.vc/portfolio/", "middle_east"),
}
GETRO_JOB_QUERIES = ("engineer", "developer", "AI")
GETRO_COMPANY_QUERIES = ("AI", "video", "generative", "creative", "audio", "image", "agents", "content")
CONSIDER_JOB_TYPES = ("software-engineer", "machine-learning-engineer", "ai-engineer", "backend-engineer")
ATS_HOSTS = ("ashbyhq.com", "lever.co", "greenhouse.io", "workable.com", "notion.site", "getro.com", "linkedin.com", "wellfound.com", "teamtailor.com", "personio", "recruitee.com", "breezy.hr", "bamboohr.com", "smartrecruiters.com", "factorialhr.com", "factorial.com", "join.com", "homerun.co", "jobvite.com", "icims.com", "myworkdayjobs.com", "dover.com", "keka.com", "freshteam.com", "zohorecruit", "gem.com", "rippling.com", "news.ycombinator.com", "jobs.")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    return s


def _iso_from_epoch(ts: Any) -> Optional[str]:
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return None
    if ts > 1e12:
        ts /= 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def domain_of(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    host = host.split(":")[0]
    host = re.sub(r"^(www|careers|jobs|apply|join|work)\.", "", host)
    if not host or any(h in host for h in ATS_HOSTS):
        return None
    return host


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _salary_text(raw: Optional[dict]) -> Optional[str]:
    if not raw or not (raw.get("min") or raw.get("max")):
        return None
    lo, hi = raw.get("min"), raw.get("max")
    rng = f"{int(lo):,}–{int(hi):,}" if lo and hi else f"{int(lo or hi):,}"
    return f"{raw.get('currency') or ''} {rng}/{raw.get('period') or 'year'}".strip()


def getro_jobs(fund: str, network_id: int, pages: int = 2) -> list[dict[str, Any]]:
    s = _session()
    seen: set[int] = set()
    out = []
    for q in GETRO_JOB_QUERIES:
        for page in range(pages):
            r = s.post(
                f"https://api.getro.com/api/v2/collections/{network_id}/search/jobs",
                json={"hits_per_page": 100, "page": page, "query": q, "filters": {"work_mode": ["remote"]}},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            jobs = r.json().get("results", {}).get("jobs", [])
            for j in jobs:
                if j["id"] in seen:
                    continue
                seen.add(j["id"])
                org = j.get("organization") or {}
                cents_lo, cents_hi = j.get("compensation_amount_min_cents"), j.get("compensation_amount_max_cents")
                period = (j.get("compensation_period") or "").replace("period_not_defined", "") or "year"
                salary_raw = None
                if cents_lo or cents_hi:
                    salary_raw = {"min": (cents_lo or 0) / 100 or None, "max": (cents_hi or 0) / 100 or None, "currency": j.get("compensation_currency"), "period": period}
                locs = j.get("searchable_locations") or j.get("locations") or []
                out.append({
                    "kind": "role",
                    "dedup_key": f"getro:{j['id']}",
                    "company": (org.get("name") or "").strip(),
                    "domain": domain_of(j.get("url")),
                    "fund": fund,
                    "source": "getro",
                    "role_title": j.get("title"),
                    "job_url": j.get("url"),
                    "locations": locs,
                    "region": region_of(locs),
                    "salary_raw": salary_raw,
                    "salary": _salary_text(salary_raw),
                    "team_size": team_size(org.get("head_count"), bucketed=True),
                    "stage": org.get("stage"),
                    "tags": org.get("industry_tags"),
                    "description": ", ".join(org.get("industry_tags") or []),
                    "posted_at": _iso_from_epoch(j.get("created_at")),
                    "job_text": j.get("work_mode") or "",
                })
            if len(jobs) < 100:
                break
    return out


def getro_companies(fund: str, network_id: int) -> list[dict[str, Any]]:
    s = _session()
    seen: set[int] = set()
    out = []
    for q in GETRO_COMPANY_QUERIES:
        r = s.post(
            f"https://api.getro.com/api/v2/collections/{network_id}/search/companies",
            json={"hits_per_page": 100, "page": 0, "query": q},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        for c in r.json().get("results", {}).get("companies", []):
            if c["id"] in seen or not c.get("domain"):
                continue
            seen.add(c["id"])
            locs = c.get("locations") or []
            out.append({
                "kind": "founder",
                "dedup_key": f"co:{c['domain'].lower()}",
                "company": (c.get("name") or "").strip(),
                "domain": c["domain"].lower().removeprefix("www."),
                "company_url": f"https://{c['domain']}",
                "fund": fund,
                "source": "getro",
                "locations": locs,
                "region": region_of(locs),
                "team_size": team_size(c.get("head_count"), bucketed=True),
                "stage": c.get("stage"),
                "tags": c.get("industry_tags"),
                "description": c.get("description") or "",
                "active_jobs": c.get("active_jobs_count") or 0,
            })
    return out


def consider_jobs(fund: str, base_url: str, board_id: str) -> list[dict[str, Any]]:
    s = _session()
    page = s.get(f"{base_url}/jobs", timeout=TIMEOUT, headers={"Accept": "text/html"})
    page.raise_for_status()
    m = re.search(r'"csrfToken":"([^"]+)"', page.text)
    if not m:
        raise RuntimeError("no csrf token")
    headers = {"x-csrf-token": m.group(1), "Content-Type": "application/json"}
    seen: set[str] = set()
    out = []
    for jt in CONSIDER_JOB_TYPES:
        meta: dict[str, Any] = {"size": 100}
        for _ in range(2 if jt == "software-engineer" else 1):
            r = s.post(
                f"{base_url}/api-boards/search-jobs",
                headers=headers,
                json={"meta": meta, "board": {"id": board_id, "isParent": True}, "query": {"remoteOnly": True, "jobTypes": [jt]}},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            body = r.json()
            for j in body.get("jobs", []):
                jid = j.get("jobId") or j.get("url")
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                sal = j.get("salary") or {}
                salary_raw = None
                if sal.get("minValue") or sal.get("maxValue"):
                    salary_raw = {
                        "min": sal.get("minValue"), "max": sal.get("maxValue"),
                        "currency": (sal.get("currency") or {}).get("value"),
                        "period": (sal.get("period") or {}).get("value") or "year",
                    }
                locs = list(j.get("locations") or [])
                regions = [x.get("label") for x in j.get("regions") or []]
                markets = [x.get("label") for x in j.get("markets") or []]
                out.append({
                    "kind": "role",
                    "dedup_key": f"consider:{jid}",
                    "company": (j.get("companyName") or "").strip(),
                    "domain": (j.get("companyDomain") or "").lower() or None,
                    "company_url": f"https://{j['companyDomain']}" if j.get("companyDomain") else None,
                    "fund": fund,
                    "source": "consider",
                    "role_title": j.get("title"),
                    "job_url": j.get("applyUrl") or j.get("url"),
                    "locations": locs + regions,
                    "region": region_of([x.get("label") for x in j.get("normalizedLocations") or []] + regions),
                    "salary_raw": salary_raw,
                    "salary": _salary_text(salary_raw),
                    "team_size": j.get("companyStaffCount"),
                    "stage": ", ".join(x.get("label") for x in j.get("stages") or []),
                    "tags": markets,
                    "description": ", ".join(markets),
                    "posted_at": j.get("timeStamp"),
                    "job_text": "contractor" if j.get("contractor") else "",
                })
            seq = (body.get("meta") or {}).get("sequence")
            if not seq or len(body.get("jobs", [])) < 100:
                break
            meta = {"size": 100, "sequence": seq}
    return out


def _next_data(url: str) -> dict[str, Any]:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError(f"no __NEXT_DATA__ at {url}")
    return json.loads(m.group(1))["props"]["pageProps"]


def speedrun_companies(prefilter: Optional[Callable[[dict], bool]] = None) -> list[dict[str, Any]]:
    listing = _next_data("https://speedrun.a16z.com/companies")["companies"]["results"]
    picked = []
    for c in listing:
        lead = {
            "kind": "founder",
            "company": c.get("name", "").strip(),
            "fund": "a16z speedrun",
            "source": "speedrun",
            "locations": [x for x in (c.get("city"), c.get("state"), c.get("country")) if x],
            "region": region_of([c.get("country"), c.get("region")]),
            "team_size": c.get("team_size"),
            "stage": c.get("cohort"),
            "tags": c.get("industries"),
            "description": f"{c.get('preamble') or ''} {', '.join(c.get('industries') or [])}",
            "_slug": c.get("slug"),
        }
        if prefilter is None or prefilter(lead):
            picked.append(lead)

    def detail(lead: dict[str, Any]) -> Optional[dict[str, Any]]:
        try:
            c = _next_data(f"https://speedrun.a16z.com/companies/{lead['_slug']}")["company"]
        except Exception:
            return None
        site = c.get("website_url")
        lead["domain"] = domain_of(site)
        lead["company_url"] = site
        lead["description"] = f"{c.get('preamble') or ''} {c.get('description') or ''} {', '.join(c.get('industries') or [])}"
        lead["founders"] = [
            {
                "name": f"{f.get('first_name', '')} {f.get('last_name', '')}".strip(),
                "title": f.get("title"),
                "linkedin": f.get("linkedin_url"),
            }
            for f in c.get("founder_set") or []
        ]
        lead["dedup_key"] = f"co:{lead['domain']}" if lead["domain"] else f"speedrun:{lead['_slug']}"
        return lead

    with ThreadPoolExecutor(8) as ex:
        return [d for d in ex.map(detail, picked) if d]


def ats_jobs(company: str, domain: Optional[str], fund: str, base: dict[str, Any]) -> list[dict[str, Any]]:
    slugs = {_slug(company).replace("-", ""), _slug(company)}
    if domain:
        slugs.add(domain.split(".")[0])
    out: list[dict[str, Any]] = []
    s = _session()
    for slug in [x for x in slugs if x]:
        try:
            r = s.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"}, timeout=10)
            if r.ok:
                for j in r.json().get("jobs", []):
                    if not (j.get("isRemote") or j.get("workplaceType") == "Remote"):
                        continue
                    out.append(_ats_lead(base, f"ashby:{slug}:{j.get('id')}", j.get("title"), j.get("jobUrl"), [j.get("location") or "", "Remote"], j.get("publishedAt"), j.get("descriptionPlain") or ""))
                if out:
                    return out
            r = s.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, timeout=10)
            if r.ok and isinstance(r.json(), list):
                for j in r.json():
                    cat = j.get("categories") or {}
                    if j.get("workplaceType") != "remote" and "remote" not in (cat.get("location") or "").lower():
                        continue
                    out.append(_ats_lead(base, f"lever:{slug}:{j.get('id')}", j.get("text"), j.get("hostedUrl"), [cat.get("location") or "", "Remote"], _iso_from_epoch(j.get("createdAt")), j.get("descriptionPlain") or ""))
                if out:
                    return out
            r = s.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=10)
            if r.ok:
                for j in r.json().get("jobs", []):
                    loc = (j.get("location") or {}).get("name") or ""
                    if "remote" not in loc.lower():
                        continue
                    out.append(_ats_lead(base, f"gh:{slug}:{j.get('id')}", j.get("title"), j.get("absolute_url"), [loc], j.get("updated_at"), ""))
                if out:
                    return out
        except (requests.RequestException, ValueError):
            continue
    return out


def _ats_lead(base: dict[str, Any], key: str, title: Optional[str], url: Optional[str], locs: list[str], posted: Optional[str], text: str) -> dict[str, Any]:
    return {
        **{k: v for k, v in base.items() if not k.startswith("_")},
        "kind": "role",
        "dedup_key": key,
        "role_title": title,
        "job_url": url,
        "locations": [x for x in locs if x],
        "posted_at": posted,
        "job_text": text[:4000],
    }


_TAG = re.compile(r"<[^>]+>")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_HREF = re.compile(r'href="([^"]+)"')


def hn_who_is_hiring(max_posts: int = 600) -> list[dict[str, Any]]:
    hits = requests.get(
        "https://hn.algolia.com/api/v1/search_by_date",
        params={"tags": "story,author_whoishiring", "query": "who is hiring", "hitsPerPage": 5},
        timeout=TIMEOUT,
    ).json()["hits"]
    story = next(h for h in hits if h["title"].lower().startswith("ask hn: who is hiring"))
    item = requests.get(f"https://hn.algolia.com/api/v1/items/{story['objectID']}", timeout=40).json()
    out = []
    for c in (item.get("children") or [])[:max_posts]:
        raw = c.get("text") or ""
        if "remote" not in raw.lower():
            continue
        text = html.unescape(_TAG.sub("\n", raw.replace("<p>", "\n")))
        header = text.strip().split("\n", 1)[0]
        parts = [p.strip() for p in header.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        company = re.sub(r"\s*\(.*?\)\s*", " ", parts[0]).strip()
        hrefs = [html.unescape(h) for h in _HREF.findall(raw)]
        site = next((h for h in hrefs if domain_of(h)), None)
        emails = [e for e in _EMAIL.findall(text) if not e.lower().startswith(("jobs@", "careers@", "hr@", "recruiting@", "talent@"))] or _EMAIL.findall(text)
        out.append({
            "kind": "role",
            "dedup_key": f"hn:{c['id']}",
            "company": company[:80],
            "domain": domain_of(site),
            "company_url": site,
            "fund": "HN Who is Hiring",
            "source": "hn",
            "role_title": None,
            "_parts": parts,
            "job_url": f"https://news.ycombinator.com/item?id={c['id']}",
            "locations": [p for p in parts if re.search(r"remote|onsite|on-site|hybrid|worldwide|anywhere|global|time ?zone|\b(utc|gmt|cet|est|pst|ist)\b", p, re.I)],
            "region": region_of(header),
            "description": text[:1500],
            "posted_at": c.get("created_at"),
            "job_text": text[:4000],
            "contact_email": emails[0] if emails else None,
        })
    return out


_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)


def _clean(text: str) -> str:
    text = html.unescape(_TAG.sub(" ", text))
    return re.sub(r"\s+", " ", text).strip()


def fetch_job_text(url: Optional[str], limit: int = 6000) -> str:
    if not url or "news.ycombinator.com" in url:
        return ""
    m = re.match(r"https?://jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url)
    try:
        if m:
            r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}", timeout=12)
            if r.ok:
                for j in r.json().get("jobs", []):
                    if j.get("id") == m.group(2):
                        return (j.get("descriptionPlain") or _clean(j.get("descriptionHtml") or ""))[:limit]
        m = re.match(r"https?://jobs\.lever\.co/([^/?#]+)/([0-9a-f-]{36})", url)
        if m:
            r = requests.get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}", timeout=12)
            if r.ok:
                j = r.json()
                parts = [j.get("descriptionPlain") or ""] + [f"{x.get('text')}: {_clean(x.get('content') or '')}" for x in j.get("lists") or []]
                return " ".join(parts)[:limit]
        r = requests.get(url, headers={"User-Agent": UA}, timeout=12)
        if not r.ok:
            return ""
        body = r.text
        text = _clean(_SCRIPT_STYLE.sub(" ", body))
        if len(text) < 600:
            text = _clean(body.replace("\\n", " ").replace("\\u003c", "<").replace("\\u003e", ">"))
        return text[:limit]
    except (requests.RequestException, ValueError):
        return ""


_SOCIAL = re.compile(r"linkedin|twitter|x\.com|facebook|instagram|youtube|medium\.com|crunchbase|apple\.com|google\.com|github|tiktok|vimeo", re.I)
_ANCHOR = re.compile(r"<a\b[^>]*href=\"(https?://[^\"]+)\"[^>]*>(.*?)</a>", re.S | re.I)


def portfolio_page_text(url: str, limit: int = 160_000) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    fund_host = urlparse(r.url).netloc.replace("www.", "").split(".")[0]
    body = _SCRIPT_STYLE.sub(" ", r.text)

    def annotate(m: re.Match) -> str:
        host = urlparse(m.group(1)).netloc.lower().replace("www.", "")
        inner = m.group(2)
        if not host or fund_host in host or _SOCIAL.search(host):
            return inner
        return f"{inner} [{host}]"

    text = _clean(_ANCHOR.sub(annotate, body))
    scripts = " ".join(re.findall(r'"name":"[^"]{1,80}","url":"https?://[^"]+","description":"[^"]{0,300}"', r.text))
    return (text + " " + scripts)[:limit]


HUB_COUNTRIES = {"NO": "Norway"}
HUB_SIZES = {"1-10": 5, "11-50": 30}
HUB_FUNDED_STAGES = {"seed", "seriesa", "seriesb", "seriesc", "seriesd", "growth"}


def thehub_companies(code: str, country: str) -> list[dict[str, Any]]:
    s = _session()

    def page(size: str, n: int) -> dict[str, Any]:
        r = s.get("https://thehub.io/api/companies", params={"countryCodes": code, "numberOfEmployees": size, "page": n}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    docs: list[dict[str, Any]] = []
    for size in HUB_SIZES:
        first = page(size, 1)
        docs.extend(first.get("docs", []))
        with ThreadPoolExecutor(8) as ex:
            for body in ex.map(lambda n: page(size, n), range(2, (first.get("pages") or 1) + 1)):
                docs.extend(body.get("docs", []))

    out = []
    for d in docs:
        domain = domain_of(d.get("website"))
        if not domain:
            continue
        countries = [((c.get("location") or {}).get("country")) for c in d.get("countries") or []]
        founded = str(d.get("founded") or "").strip()
        out.append({
            "kind": "founder",
            "dedup_key": f"co:{domain}",
            "company": (d.get("name") or "").strip()[:80],
            "domain": domain,
            "company_url": d.get("website"),
            "fund": f"The Hub ({country})",
            "source": "thehub",
            "locations": [c for c in countries if c] or [country],
            "region": "europe",
            "team_size": HUB_SIZES.get(d.get("numberOfEmployees")),
            "stage": " · ".join(x for x in (d.get("fundingStage"), f"founded {founded}" if founded else "") if x),
            "founded": int(founded) if founded.isdigit() else None,
            "tags": d.get("industries"),
            "description": f"{(d.get('whatWeDo') or '')[:700]} {', '.join(d.get('industries') or [])}",
            "active_jobs": d.get("numberOfActiveJobs") or 0,
            "funded": (d.get("fundingStage") or "").lower() in HUB_FUNDED_STAGES,
            "funding": d.get("fundingStage"),
        })
    return out
