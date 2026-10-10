import re
from datetime import datetime, timezone
from typing import Any, Optional

EUROPE = (
    "europe", "united kingdom", "uk", "england", "london", "scotland", "ireland", "dublin", "germany", "berlin",
    "munich", "hamburg", "france", "paris", "netherlands", "amsterdam", "belgium", "brussels", "spain", "madrid",
    "barcelona", "portugal", "lisbon", "italy", "milan", "rome", "switzerland", "zurich", "geneva", "austria",
    "vienna", "sweden", "stockholm", "norway", "oslo", "denmark", "copenhagen", "finland", "helsinki", "estonia",
    "tallinn", "latvia", "riga", "lithuania", "vilnius", "poland", "warsaw", "krakow", "czech", "prague",
    "slovakia", "hungary", "budapest", "romania", "bucharest", "bulgaria", "sofia", "greece", "athens", "croatia",
    "serbia", "belgrade", "slovenia", "luxembourg", "iceland", "cyprus", "malta", "ukraine", "kyiv",
)
MIDDLE_EAST = (
    "middle east", "mena", "united arab emirates", "uae", "dubai", "abu dhabi", "saudi", "riyadh", "jeddah",
    "qatar", "doha", "bahrain", "kuwait", "oman", "muscat", "israel", "tel aviv", "egypt", "cairo", "jordan",
    "amman", "turkey", "istanbul", "lebanon", "beirut",
)
INDIA = (
    "india", "bengaluru", "bangalore", "mumbai", "delhi", "new delhi", "hyderabad", "pune", "chennai",
    "gurgaon", "gurugram", "noida", "kolkata",
)
US = (
    "united states", "usa", "u.s.", "us", "san francisco", "new york", "nyc", "seattle", "austin", "boston",
    "los angeles", "palo alto", "california", "north america", "canada", "toronto",
)

_WORLDWIDE_LOC = re.compile(r"\b(worldwide|anywhere|global|international|any ?where in the world|all time ?zones|any time ?zone)\b", re.I)
_WORLDWIDE = re.compile(
    r"\b(remote[- ]?\(?(worldwide|global|anywhere)|work from anywhere|anywhere in the world|fully distributed team|"
    r"hire (from )?(anywhere|globally|worldwide)|any time ?zone|all time ?zones|location[- ]independent|"
    r"(open to|hiring) (candidates )?(worldwide|globally|from anywhere))",
    re.I,
)
_REMOTE_PAREN = re.compile(
    r"remote\s*[\(\[]\s*(us|usa|u\.s\.|uk|eu|europe|canada|north america|americas|latam|emea|cet|est|pst|germany|france|"
    r"spain|netherlands|poland|nordics|dach)\b[^\)\]]*[\)\]]",
    re.I,
)
_ASIA = re.compile(r"(?i:\b(apac|asia|asia[- ]pacific)\b|(gmt|utc) ?\+ ?5:?30)|\bIST\b")
_RESTRICTED = re.compile(
    r"\b(us|u\.s\.|usa|united states|uk|eu|europe|canada|north america)[- ]?(only|based only|residents? only)\b|"
    r"must (be )?(based|located|reside|live) in (the )?(us|u\.s\.|usa|united states|uk|eu|europe|canada|germany|france)|"
    r"(authori[sz]ed|eligible|right) to work in (the )?(us|u\.s\.|usa|united states|uk|eu|canada)|"
    r"\b(us|u\.s\.)[- ]based (candidates|applicants)|security clearance|no visa sponsorship|"
    r"within (the )?(us|eu|uk|cet|est|pst) (time ?zones?|hours)",
    re.I,
)
_EOR = re.compile(r"\b(deel|remote\.com|oyster|rippling eor|employer of record|eor|contractor|b2b contract)\b", re.I)

_ROLE_STRONG = re.compile(
    r"\b(ai|a\.i\.|ml|llm|genai|generative|agent(s|ic)?|applied ai|machine learning|founding engineer|"
    r"forward[- ]deployed|creative technologist)\b",
    re.I,
)
_ROLE_OK = re.compile(
    r"\b(full[- ]?stack|back[- ]?end|software (engineer|developer)|product engineer|platform engineer|"
    r"python|typescript|node(\.js)?|member of technical staff|mts|research engineer|engineer)\b",
    re.I,
)
_ROLE_BAD = re.compile(
    r"\b(manager|director|head of|vp|vice president|principal|(?<!technical )staff|sales|account (executive|manager)|"
    r"marketing|recruit(er|ing)|talent|designer|intern(ship)?|android|ios|embedded|firmware|hardware|"
    r"mechanical|electrical|analyst|support|customer success|solutions?|sales engineer|consultant|counsel|"
    r"legal|finance|accountant|operations|qa|quality assurance|test engineer|security engineer|privacy|"
    r"network engineer|sre|site reliability|data center|technician|clinical|nurse|teacher|chief|gtm|"
    r"go[- ]to[- ]market|growth|program|data scientist|scientist|researcher|phd|analytics|"
    r"(with|speaking|fluent) (french|german|spanish|italian|japanese|korean|mandarin|portuguese|dutch|arabic|polish)|"
    r"(french|german|spanish|italian|japanese|dutch|arabic)[- ]speaking|"
    r"(spanish|french|german|portuguese|japanese|italian|dutch|arabic) ?/ ?english|english ?/ ?(spanish|french|german|portuguese|japanese|italian|dutch|arabic))\b",
    re.I,
)
_ROLE_NOUN = re.compile(r"\b(engineers?|developers?|technologist|mts|member of technical staff|programmer|hacker)\b", re.I)
_ROLE_ML = re.compile(
    r"\b(ml|machine learning|nlp|natural language|computer vision|cv|deep learning|data scien\w*|research|"
    r"inference|training|mlops|ml ?ops|speech|perception|robotics|recommend\w*|ranking|search relevance|"
    r"pytorch|cuda|gpu|kernel|compiler|reinforcement learning|rl)\b",
    re.I,
)
_ROLE_APPLIED = re.compile(
    r"\b(llm|genai|gen ai|generative ai|agents?|agentic|applied ai|ai engineer|ai product|ai application|"
    r"full[- ]?stack|back[- ]?end|product engineer|founding engineer|forward[- ]deployed|ai developer|"
    r"ai software|software engineer,? ai|creative technologist)\b",
    re.I,
)
_SENIOR = re.compile(r"\b(senior|sr\.?|lead|ii|iii)\b", re.I)

CREATIVE_TERMS = (
    "video", "videos", "image generation", "images", "audio", "music", "creative", "creatives", "creator", "creators",
    "content creation", "ugc", "avatar", "avatars", "animation", "3d", "film", "editing", "photo", "photos",
    "photography", "storytelling", "visual effects", "generative media", "text-to-video", "text-to-image",
    "image editing", "video editing", "voice cloning", "dubbing", "motion graphics",
)
CREATIVE_WEAK = ("design", "media", "voice", "advertising", "ads", "marketing content", "social media", "game", "games", "visual", "branding")
AI_TERMS = (
    "ai", "artificial intelligence", "llm", "machine learning", "agent", "agents", "agentic", "genai",
    "generative", "foundation model", "copilot", "automation", "nlp", "computer vision", "rag",
)


def _blob(*parts: Any) -> str:
    out = []
    for p in parts:
        if not p:
            continue
        if isinstance(p, (list, tuple, set)):
            out.extend(str(x) for x in p if x)
        else:
            out.append(str(p))
    return " ".join(out).lower()


def _has_any(text: str, terms: tuple[str, ...]) -> list[str]:
    return [t for t in terms if re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", text)]


def region_of(*parts: Any) -> str:
    text = _blob(*parts)
    if _has_any(text, INDIA):
        return "india"
    if _has_any(text, MIDDLE_EAST):
        return "middle_east"
    if _has_any(text, EUROPE):
        return "europe"
    if _has_any(text, US):
        return "us"
    if _WORLDWIDE_LOC.search(text):
        return "global"
    if _ASIA.search(text):
        return "apac"
    return "other"


def _loc_items(locations: Any) -> list[str]:
    items = locations if isinstance(locations, (list, tuple)) else [locations]
    out = []
    for item in items:
        if item:
            out.extend(p.strip().lower() for p in re.split(r"[,;/|]", str(item)) if p.strip())
    return out


def eligibility(locations: Any, text: str = "") -> tuple[str, str]:
    items = _loc_items(locations)
    loc = " ".join(items)
    body = _blob(text)
    both = f"{loc} {body}"
    if _has_any(loc, INDIA):
        return "yes", "lists India"
    if _RESTRICTED.search(both) or _REMOTE_PAREN.search(loc):
        return "no", "region-locked"
    if _WORLDWIDE_LOC.search(loc) or _WORLDWIDE.search(body):
        return "yes", "worldwide remote"
    if _ASIA.search(" ".join(str(x) for x in (locations if isinstance(locations, (list, tuple)) else [locations]) if x) + " " + (text or "")):
        return "yes", "APAC/IST friendly"
    named = [p for p in items if not re.fullmatch(r"\(?(fully )?remote( first| friendly| ok)?\)?|global|anywhere|worldwide", p)]
    remote = any("remote" in p for p in items) or "remote" in body[:400]
    if remote and not named:
        if _EOR.search(body):
            return "likely", "remote + hires via EOR/contractor"
        return "likely", "remote, no country listed"
    if remote and _EOR.search(body):
        return "unknown", "country listed but hires contractors"
    if remote:
        return "no", "remote but country-locked"
    return "no", "on-site"


def role_fit(title: str) -> tuple[int, str]:
    t = title or ""
    if _ROLE_BAD.search(t) and not re.search(r"\b(design engineer|engineering manager)\b", t, re.I):
        return 0, ""
    if len(t) > 90 or re.search(r"https?://|stack:|^not\b|\)$", t.strip(), re.I) or not _ROLE_NOUN.search(t):
        return 0, ""
    if _ROLE_ML.search(t) and not _ROLE_APPLIED.search(t):
        return 0, ""
    if _ROLE_STRONG.search(t):
        pts, why = 25, "AI/agent engineering role"
    elif _ROLE_APPLIED.search(t):
        pts, why = 22, "full-stack/backend role"
    elif _ROLE_OK.search(t):
        pts, why = 18, "engineering role"
    else:
        return 0, ""
    if _SENIOR.search(t):
        pts -= 4
    return pts, why


def _usd(amount: float, currency: str) -> float:
    rates = {"USD": 1, "EUR": 1.08, "GBP": 1.27, "CHF": 1.12, "CAD": 0.73, "AED": 0.27, "SEK": 0.095, "DKK": 0.145, "NOK": 0.093, "PLN": 0.25, "INR": 0.012}
    return amount * rates.get((currency or "USD").upper(), 1)


def salary_usd(salary: Optional[dict]) -> Optional[float]:
    if not salary:
        return None
    hi = salary.get("max") or salary.get("min")
    if not hi:
        return None
    yearly = {"year": 1, "month": 12, "hour": 2000, "week": 50, "day": 230}.get((salary.get("period") or "year").lower(), 1)
    return _usd(float(hi) * yearly, salary.get("currency") or "USD")


def _age_days(posted_at: Optional[str]) -> Optional[float]:
    if not posted_at:
        return None
    try:
        dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400


HEADCOUNT_BUCKETS = {1: 5, 2: 30, 3: 120, 4: 350, 5: 750, 6: 3000, 7: 7500, 8: 15000}


def team_size(raw: Any, bucketed: bool = False) -> Optional[int]:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if bucketed:
        return HEADCOUNT_BUCKETS.get(n)
    return n


def _company_points(lead: dict[str, Any], reasons: list[str]) -> int:
    text = _blob(lead.get("company"), lead.get("description"), lead.get("tags"))
    pts = 0
    creative = _has_any(text, CREATIVE_TERMS)
    weak = _has_any(text, CREATIVE_WEAK)
    ai = _has_any(text, AI_TERMS)
    if creative and ai:
        pts += 22
        reasons.append(f"creative AI ({', '.join(creative[:3])})")
    elif creative:
        pts += 10
        reasons.append(f"creative ({', '.join(creative[:2])})")
    elif weak and ai:
        pts += 6
        reasons.append(f"AI + {weak[0]}")
    if ai:
        pts += 10
        if not creative and not weak:
            reasons.append("AI company")
    size = lead.get("team_size")
    if size:
        if size <= 50:
            pts += 8
            reasons.append(f"~{size} people")
        elif size <= 250:
            pts += 4
            reasons.append(f"~{size} people")
        elif size > 1500:
            pts -= 25
        elif size > 600:
            pts -= 8
    founded = lead.get("founded")
    if founded:
        age = datetime.now(timezone.utc).year - int(founded)
        if age <= 2:
            pts += 7
            reasons.append(f"founded {founded}")
        elif age <= 4:
            pts += 3
            reasons.append(f"founded {founded}")
        elif age > 10:
            pts -= 5
    hq = lead.get("region")
    if hq in ("europe", "middle_east"):
        pts += 15
        reasons.append("Europe" if hq == "europe" else "Middle East")
    elif hq == "us":
        pts += 5
    elif hq == "india":
        pts -= 10
    return pts


TARGET_REGIONS = ("europe", "middle_east")
UNRESOLVED_REGIONS = ("global", "other")


VC_SOURCES = ("getro", "consider", "speedrun", "portfolio")
STAGE_LABELS = {"seed": "seed", "seriesa": "Series A", "seriesb": "Series B", "seriesc": "Series C", "seriesd": "Series D", "growth": "growth"}


def funding_status(lead: dict[str, Any]) -> tuple[Optional[bool], str]:
    if lead.get("source") in VC_SOURCES:
        return True, f"{lead.get('fund')}-backed"
    if "funded" in lead:
        stage = (lead.get("funding") or "").lower()
        return bool(lead["funded"]), f"{STAGE_LABELS.get(stage, stage)}-funded" if lead["funded"] else ""
    return None, ""


def score(lead: dict[str, Any]) -> Optional[dict[str, Any]]:
    if lead.get("region") not in TARGET_REGIONS + UNRESOLVED_REGIONS:
        return None
    funded, funded_why = funding_status(lead)
    if funded is False:
        return None
    reasons: list[str] = []
    pts = _company_points(lead, reasons)
    text = _blob(lead.get("company"), lead.get("description"), lead.get("tags"))
    is_ai = bool(_has_any(text, AI_TERMS))

    if lead["kind"] == "role":
        fit, why = role_fit(lead.get("role_title") or "")
        if not fit:
            return None
        elig, elig_why = eligibility(lead.get("locations"), lead.get("job_text") or "")
        lead["eligibility"] = elig
        if elig == "no":
            return None
        sal = salary_usd(lead.get("salary_raw"))
        if sal is not None and sal < 20000:
            return None
        pts += fit + {"yes": 30, "likely": 18, "unknown": 6}[elig]
        reasons[:0] = [why, elig_why]
        if sal:
            pts += 3
            reasons.append(f"~${int(sal / 1000)}k/yr")
        age = _age_days(lead.get("posted_at"))
        if age is not None:
            if age <= 7:
                pts += 6
                reasons.append("posted this week")
            elif age <= 21:
                pts += 3
            elif age > 60:
                pts -= 8
        if lead.get("contact_email"):
            pts += 6
            reasons.append("founder email in post")
    else:
        if not is_ai:
            return None
        if (lead.get("team_size") or 0) > 300:
            return None
        if lead.get("region") == "india":
            return None
        lead["eligibility"] = "founder_dm"
        if lead.get("founders"):
            pts += 8
            reasons.append("founders known")
        jobs = lead.get("active_jobs") or 0
        if jobs > 0:
            pts += 8 + min(jobs, 20) * 0.3
            reasons.append(f"hiring ({jobs} open roles)")
        pts += min(len(_has_any(text, CREATIVE_TERMS)), 4) * 1.5

    if funded_why:
        reasons.append(funded_why)
    lead["score"] = round(max(pts, 0), 1)
    lead["reasons"] = reasons
    return lead
