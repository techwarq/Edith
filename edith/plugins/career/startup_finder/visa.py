import csv
import io
import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from edith.plugins.career import store as career
from edith.plugins.career.startup_finder.email_draft import short_name

logger = logging.getLogger("edith.plugins.career.startup_finder.visa")

PATHS = ("sponsor", "remote", "unlikely", "unknown")

CACHE_DIR = Path.home() / ".edith" / "visa_registers"
MAX_AGE = timedelta(days=7)
UK_INDEX = "https://www.gov.uk/api/content/government/publications/register-of-licensed-sponsors-workers"
NL_REGISTER = "https://ind.nl/en/public-register-recognised-sponsors/public-register-regular-labour-and-highly-skilled-migrants"

ISO3 = {
    "GBR": "united kingdom", "NLD": "netherlands", "DEU": "germany", "NOR": "norway", "SWE": "sweden",
    "DNK": "denmark", "FIN": "finland", "ISL": "iceland", "IRL": "ireland", "FRA": "france", "BEL": "belgium",
    "LUX": "luxembourg", "CHE": "switzerland", "AUT": "austria", "ESP": "spain", "PRT": "portugal", "ITA": "italy",
    "GRC": "greece", "MLT": "malta", "CYP": "cyprus", "POL": "poland", "CZE": "czechia", "SVK": "slovakia",
    "HUN": "hungary", "ROU": "romania", "BGR": "bulgaria", "SVN": "slovenia", "HRV": "croatia", "SRB": "serbia",
    "UKR": "ukraine", "EST": "estonia", "LVA": "latvia", "LTU": "lithuania", "ARE": "united arab emirates",
    "SAU": "saudi arabia", "ISR": "israel", "QAT": "qatar", "TUR": "turkey", "USA": "united states",
    "CAN": "canada", "IND": "india",
}
ALIASES = {
    "united kingdom": ("united kingdom", "uk", "england", "scotland", "wales", "great britain", "london", "manchester", "edinburgh", "cambridge, uk", "oxford"),
    "netherlands": ("netherlands", "holland", "amsterdam", "rotterdam", "utrecht", "eindhoven", "the hague", "delft"),
    "germany": ("germany", "deutschland", "berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne", "köln", "stuttgart"),
    "czechia": ("czechia", "czech republic", "prague"),
    "united arab emirates": ("united arab emirates", "uae", "dubai", "abu dhabi"),
    "turkey": ("turkey", "türkiye", "turkiye", "istanbul"),
    "united states": ("united states", "usa", "san francisco", "new york"),
}
TLD_COUNTRY = {tld: country for country, tld in career.COUNTRY_TLDS.items()}

_SPONSOR = re.compile(
    r"\b(visa sponsorship|sponsor(s|ing)? (your |a |work )?(visa|work permit)s?|relocation (support|package|assistance|bonus)|"
    r"help (you )?relocate|blue card)\b",
    re.I,
)
_NO_SPONSOR = re.compile(
    r"\bno (visa )?sponsorship|(unable|not able|cannot|can't|do not|don't|does not|doesn't) (to )?(offer |provide )?(visa )?sponsor",
    re.I,
)
_REMOTE = re.compile(
    r"\b(remote[- ]first|fully remote|fully distributed|distributed team|remote team|work from anywhere|async[- ]first|"
    r"hire (from )?(anywhere|globally|worldwide))\b",
    re.I,
)
_LEGAL = re.compile(
    r"\s+(limited|ltd|plc|llp|lp|inc|incorporated|llc|corp|corporation|company|co|bv|b v|nv|n v|holding|holdings|"
    r"group|gmbh|ag|sa|sas|ab|as|aps|oy|uk|nl|europe|international)$"
)

_lock = threading.Lock()
_registers: dict[str, Optional[dict[str, str]]] = {}


def name_key(name: str) -> str:
    n = (name or "").lower().replace("&", " and ")
    n = re.sub(r"\(.*?\)|\bt/a\b.*$", " ", n)
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    prev = None
    while prev != n:
        prev, n = n, _LEGAL.sub("", n).strip()
    return n.replace(" ", "")


def _cache_path(code: str) -> Path:
    return CACHE_DIR / f"{code}.json"


def _read_cache(code: str) -> tuple[Optional[dict[str, str]], bool]:
    path = _cache_path(code)
    if not path.is_file():
        return None, False
    try:
        data = json.loads(path.read_text())
        fresh = datetime.now(timezone.utc) - datetime.fromisoformat(data["fetched"]) < MAX_AGE
        return data["names"], fresh
    except (ValueError, KeyError, OSError):
        return None, False


def _fetch_uk() -> dict[str, str]:
    index = requests.get(UK_INDEX, timeout=30).json()
    url = next(a["url"] for a in index["details"]["attachments"] if a.get("url", "").endswith(".csv"))
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    names: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig", errors="replace"))):
        if (row.get("Route") or "").strip() == "Skilled Worker":
            org = (row.get("Organisation Name") or "").strip()
            if key := name_key(org):
                names.setdefault(key, org)
    return names


def _fetch_nl() -> dict[str, str]:
    resp = requests.get(NL_REGISTER, timeout=60)
    resp.raise_for_status()
    names: dict[str, str] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", resp.text, re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        if not cells:
            continue
        org = re.sub(r"<[^>]+>", "", cells[0]).replace("&amp;", "&").replace("&quot;", '"').strip().strip('"')
        if org and org != "Organisation" and (key := name_key(org)):
            names.setdefault(key, org)
    return names


FETCHERS = {"uk": _fetch_uk, "nl": _fetch_nl}
REGISTER_COUNTRIES = {"united kingdom": "uk", "netherlands": "nl"}


def register(code: str) -> Optional[dict[str, str]]:
    with _lock:
        if code in _registers:
            return _registers[code]
        names, fresh = _read_cache(code)
        if not fresh:
            try:
                names = FETCHERS[code]()
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                _cache_path(code).write_text(json.dumps({"fetched": datetime.now(timezone.utc).isoformat(), "names": names}))
            except Exception as e:
                logger.warning("couldn't refresh %s sponsor register: %s", code, e)
        _registers[code] = names
        return names


def _country_in(text: str) -> Optional[str]:
    t = (text or "").lower()
    best: Optional[tuple[int, str]] = None
    names = {c: (c,) for c in ISO3.values()} | ALIASES
    for country, terms in names.items():
        for term in terms:
            m = re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", t)
            if m and (best is None or m.start() > best[0]):
                best = (m.start(), country)
    return best[1] if best else None


def country_of(lead: dict[str, Any]) -> Optional[str]:
    info = lead.get("company_info") or {}
    if (code := str(info.get("country") or "").upper()) in ISO3:
        return ISO3[code]
    if info.get("hq") and (c := _country_in(info["hq"])):
        return c
    domain = (lead.get("domain") or "").lower()
    for tld, country in TLD_COUNTRY.items():
        if domain.endswith(tld):
            return country
    locs = lead.get("locations") or []
    found = {c for c in (_country_in(str(l)) for l in (locs if isinstance(locs, list) else [locs])) if c}
    return found.pop() if len(found) == 1 else None


def _on_register(code: str, lead: dict[str, Any]) -> tuple[Optional[bool], str]:
    names = register(code)
    if names is None:
        return None, ""
    keys = {name_key(short_name(lead["company"]))}
    stem = (lead.get("domain") or "").lower().split(".")[0]
    if len(stem) >= 5:
        keys.add(name_key(stem))
    for k in keys:
        if k and k in names:
            return True, names[k]
    return False, ""


def classify(lead: dict[str, Any]) -> tuple[str, str]:
    text = " ".join(str(x) for x in (lead.get("description"), lead.get("role_title"), lead.get("_jd")) if x)
    if _SPONSOR.search(text) and not _NO_SPONSOR.search(text):
        return "sponsor", "mentions visa sponsorship or relocation"
    country = country_of(lead)
    code = REGISTER_COUNTRIES.get(country or "")
    hit, registered = _on_register(code, lead) if code else (None, "")
    if hit:
        return "sponsor", f"on {code.upper()} sponsor register as {registered}"
    if country == "germany":
        return "sponsor", "Germany: EU Blue Card, no sponsor licence needed"
    if lead.get("kind") == "role" and lead.get("eligibility") in ("yes", "likely"):
        return "remote", "role open to hiring from India or worldwide"
    if _REMOTE.search(text):
        return "remote", "remote-first team"
    if code:
        if hit is False:
            return "unlikely", f"{country.title()}, not on the sponsor register"
        return "unknown", f"{country.title()}, sponsor register unavailable"
    if country:
        return "unlikely", f"{country.title()}, no sponsorship or remote signal"
    return "unknown", "country unknown"


def apply(conn: sqlite3.Connection, lead: dict[str, Any]) -> str:
    lead["visa"], lead["visa_why"] = classify(lead)
    career.set_lead_visa(conn, lead["id"], lead["visa"], lead["visa_why"])
    return lead["visa"]


def backfill(conn: sqlite3.Connection) -> int:
    todo = career.leads_without_visa(conn)
    for lead in todo:
        apply(conn, lead)
    return len(todo)
