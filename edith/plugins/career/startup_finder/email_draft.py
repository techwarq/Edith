import html
import json
import logging
import re
from urllib.parse import urlencode
from typing import Any, Optional

from edith.plugins.career import profile
from edith.plugins.career.startup_finder import crustdata

logger = logging.getLogger("edith.plugins.career.startup_finder.email")

def _email() -> dict[str, Any]:
    return profile.section("email")


def _projects() -> dict[str, dict[str, str]]:
    return _email().get("projects") or {}


def close_for(lead: dict[str, Any]) -> str:
    return _email().get("close_sponsor" if lead.get("visa") == "sponsor" else "close_remote", "")


def attachment_name() -> str:
    return _email().get("attachment_name") or "Resume.pdf"

_LINK = re.compile(r"(?<![\w@/])((?:https?://)?(?:[a-z0-9-]+\.)+(?:ai|space|com|io|dev|co|app)(?:/[\w./-]*[\w/])?)", re.I)


def contact_rank(title: Optional[str]) -> int:
    t = (title or "").lower()
    if "founder" in t:
        return 0
    if re.search(r"\b(cto|chief technology)\b", t):
        return 1
    if re.search(r"\b(ceo|chief executive)\b", t):
        return 2
    if re.search(r"(head|vp|vice president|director) of (engineering|ai|technology)", t):
        return 3
    return 4


def pick_recipient(lead: dict[str, Any]) -> Optional[dict[str, Any]]:
    people = [p for p in lead.get("founders") or [] if p.get("email")]
    if people:
        return min(people, key=lambda p: contact_rank(p.get("title")))
    if lead.get("contact_email"):
        return {"name": None, "email": lead["contact_email"]}
    return None


def _first_name(name: Optional[str]) -> str:
    return (name or "").split()[0].lower() if name and name.strip() else ""


_SUFFIX = re.compile(r"[\s,]+(inc|llc|ltd|limited|gmbh|ag|as|asa|ab|aps|oy|bv|b\.v\.|sa|sas|srl|plc|co)\.?$", re.I)


def short_name(company: str) -> str:
    return _SUFFIX.sub("", company.strip()).strip() or company.strip()


def subject_for(focus: str) -> str:
    focus = re.sub(r"^(an?\s+)?(engineer\s+)?(who\s+)?(builds?\s+)?", "", (focus or "").strip().lower()).strip(" .-")
    if not focus or len(focus.split()) > 5 or len(focus) > 40:
        focus = _email().get("default_focus", "ai products")
    return _email().get("subject", "{focus}").format(focus=focus)


def project_keys(projects: str) -> list[str]:
    keys = [k.strip().lower().replace("-", "") for k in (projects or "").split(",")]
    keys = list(dict.fromkeys(k for k in keys if k in _projects()))[:3]
    return keys or list(_email().get("default_projects") or list(_projects())[:2])


def compose(
    lead: dict[str, Any], like: str, projects: str = "", recipient: Optional[dict[str, Any]] = None, focus: str = "",
) -> dict[str, Any]:
    recipient = recipient if recipient is not None else pick_recipient(lead)
    first = _first_name((recipient or {}).get("name"))
    company = short_name(lead["company"]).lower()
    like = like.strip().rstrip(".").lower()
    if lead.get("kind") == "role" and lead.get("role_title"):
        hook = f"i just applied for the {lead['role_title'].lower()} role at {company}" + (f" and like that you're {like}." if like else ".")
    else:
        hook = f"i came across {company} and " + (f"like that you're {like}." if like else "wanted to reach out directly.")
    portfolio = profile.require().get("portfolio_url")
    bullets = [_projects()[k]["line"] for k in project_keys(projects)] + ([f"portfolio: {portfolio}"] if portfolio else [])
    body = (
        f"hello{' ' + first if first else ''},\n\n{_email().get('intro', '')}\n\n{hook}\n\n"
        + "\n".join(f"- {b}" for b in bullets)
        + f"\n\n{close_for(lead)}\n\n{_email().get('signoff', '')}"
    )
    return {"to": (recipient or {}).get("email"), "to_name": (recipient or {}).get("name"), "subject": subject_for(focus), "body": body}


def for_recipient(body: str, name: Optional[str]) -> str:
    first = _first_name(name)
    if not first:
        return body
    return re.sub(r"\A(hello|hi|hey)\b[^\n,]*,", lambda m: f"{m.group(1)} {first},", body, count=1, flags=re.I)


def utm_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", short_name(text or "").lower()).strip("-")


def _tracked(href: str, campaign: Optional[str], content: Optional[str]) -> str:
    host = re.sub(r"^https?://(www\.)?", "", href.lower()).split("/")[0]
    if not campaign or host not in (_email().get("tracked_hosts") or []):
        return href
    params = {"utm_source": "email", "utm_medium": "cold_email", "utm_campaign": campaign}
    if content:
        params["utm_content"] = content
    sep = "&" if "?" in href else ("?" if re.search(r"https?://[^/]+/", href) else "/?")
    return href + sep + urlencode(params)


def to_html(body: str, campaign: Optional[str] = None, content: Optional[str] = None) -> str:
    def link(m: re.Match) -> str:
        url = m.group(1)
        href = url if url.lower().startswith("http") else f"https://{url}"
        return f'<a href="{html.escape(_tracked(href, campaign, content))}">{html.escape(url)}</a>'

    out = []
    for line in body.split("\n"):
        out.append(_LINK.sub(link, html.escape(line, quote=False)))
    return '<div style="font-family:Arial,sans-serif;font-size:14px">' + "<br>".join(out) + "</div>"


def personalize(genai_client: Any, model: str, resume: str, leads: list[dict[str, Any]]) -> dict[int, tuple[str, str, str]]:
    if not leads or genai_client is None:
        return {}
    items = []
    for l in leads:
        facts = crustdata.format_info(l["company_info"]) if l.get("company_info") else ""
        items.append({"id": l["id"], "company": l["company"], "role": l.get("role_title"),
                      "about": (l.get("description") or "")[:600], "facts": facts})
    me = profile.require()
    name = me.get("name", "the sender")
    hints = "; ".join(f"{k} = {v.get('hint', v['line'])}" for k, v in _projects().items())
    subject = _email().get("subject", "{focus}").replace("{focus}", "___")
    focus_options = _email().get("focus_options") or "ai agents, llm apps, ai products, rag pipelines, ai evals"
    prompt = (
        f"You personalize a short cold email from {name}, an engineer, to a startup founder. The rest of the email is "
        "fixed; you pick three things per startup, all lowercase, casual, specific, no hype words.\n"
        "1. like: completes the sentence \"i like that you're ...\" with what the company concretely does or is "
        "betting on, from the about/facts ONLY (max 20 words, no trailing period). Never invent facts.\n"
        f"2. projects: comma-separated keys of their 2-3 projects most relevant to THIS startup, most relevant first, "
        f"from: {hints}.\n"
        f"3. focus: completes the subject line \"{subject}\" — 2-4 lowercase words naming the kind of thing they "
        f"build that matches THIS startup best, and that their resume genuinely backs up. Pick from or close to: "
        f"{focus_options}.\n\n"
        f"THEIR RESUME: {resume[:2000]}\n\n"
        "Return JSON only: {\"<id>\": {\"like\": str, \"projects\": str, \"focus\": str}}\n\n"
        f"{json.dumps(items)}"
    )
    try:
        resp = genai_client.models.generate_content(model=model, contents=prompt)
        m = re.search(r"\{.*\}", resp.text or "", re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        logger.warning("email personalization failed: %s", e)
        return {}
    out: dict[int, tuple[str, str, str]] = {}
    for k, v in data.items():
        if str(k).isdigit() and isinstance(v, dict):
            projects = v.get("projects") or ""
            if isinstance(projects, list):
                projects = ",".join(str(x) for x in projects)
            out[int(k)] = (str(v.get("like") or ""), str(projects), str(v.get("focus") or ""))
    return out
