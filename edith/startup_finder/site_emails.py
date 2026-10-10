import html
import logging
import re
from typing import Optional

import requests

logger = logging.getLogger("edith.startup_finder.site_emails")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
TIMEOUT = 8
PAGES = ("", "/contact", "/contact-us", "/about", "/about-us", "/team", "/company", "/kontakt", "/om-oss", "/impressum")
EMAIL = re.compile(r"[a-z0-9][a-z0-9._%+-]{0,63}@(?:[a-z0-9-]+\.)+[a-z]{2,}", re.I)
CF_EMAIL = re.compile(r'data-cfemail="([0-9a-f]+)"', re.I)
JUNK_LOCAL = re.compile(r"^(no-?reply|do-?not-?reply|privacy|gdpr|dpo|legal|abuse|postmaster|webmaster|invoice|billing|"
                        r"accounting|faktura|press|media|unsubscribe|example|name|your|email|user)\b", re.I)
JUNK_HOST = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js)$|sentry|wixpress|example\.", re.I)
PREFERRED = ("founders", "founder", "ceo", "cto", "hello", "hi", "hey", "team", "contact", "post", "info", "kontakt",
             "jobs", "careers", "work", "talent", "support")


def _decode_cf(hexstr: str) -> str:
    key = int(hexstr[:2], 16)
    try:
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except ValueError:
        return ""


def _on_domain(email: str, domain: str) -> bool:
    host = email.rsplit("@", 1)[1].lower()
    root = domain.lower().removeprefix("www.")
    return host == root or host.endswith("." + root) or root.endswith("." + host)


def emails_on_page(text: str, domain: str) -> list[str]:
    text = html.unescape(text)
    found = EMAIL.findall(text) + [_decode_cf(h) for h in CF_EMAIL.findall(text)]
    out = []
    for e in found:
        e = e.strip(".").lower()
        if not EMAIL.fullmatch(e):
            continue
        local = e.split("@", 1)[0]
        if JUNK_HOST.search(e) or JUNK_LOCAL.match(local) or not _on_domain(e, domain):
            continue
        if e not in out:
            out.append(e)
    return out


def find(domain: str, max_pages: int = len(PAGES)) -> list[str]:
    emails: list[str] = []
    base = f"https://{domain.lower().removeprefix('www.')}"
    for path in PAGES[:max_pages]:
        try:
            resp = requests.get(base + path, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True)
        except requests.exceptions.RequestException:
            continue
        if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", "html"):
            continue
        for e in emails_on_page(resp.text, domain):
            if e not in emails:
                emails.append(e)
        if len(emails) >= 3:
            break
    return emails


def best(emails: list[str], first_names: list[str]) -> tuple[Optional[str], Optional[str]]:
    names = [n.lower() for n in first_names if n]
    for e in emails:
        local = e.split("@", 1)[0]
        for n in names:
            if local == n or local.startswith(n + ".") or local.startswith(n + "_"):
                return e, n
    rank = {p: i for i, p in enumerate(PREFERRED)}
    ordered = sorted(emails, key=lambda e: rank.get(e.split("@", 1)[0], len(rank)))
    return (ordered[0], None) if ordered else (None, None)
