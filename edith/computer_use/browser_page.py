from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Optional

BRAVE_BUNDLE_ID = "com.brave.Browser"
BRAVE_APP_NAME = "Brave Browser"
MAX_PAGE_ELEMENTS = 120
_TIMEOUT_SECONDS = 10

ENABLE_INSTRUCTIONS = (
    "Brave blocks page scripting by default. Turn it on once: in Brave's menu bar choose "
    "View → Developer → Allow JavaScript from Apple Events."
)


class BrowserError(Exception):
    pass


class BrowserScriptingOff(BrowserError):
    pass


@dataclass(frozen=True)
class PageElement:
    id: str
    tag: str
    role: str
    label: str
    value: str
    placeholder: str
    editable: bool
    enabled: bool
    checked: Optional[bool]
    focused: bool
    secure: bool
    position: str
    in_view: bool


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    title: str
    elements: list[PageElement]
    text: list[str]


def _run_js(js: str) -> str:
    literal = js.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "{BRAVE_APP_NAME}" to execute front window\'s active tab javascript "{literal}"'
    try:
        out = subprocess.run(["osascript", "-"], input=script, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as e:
        raise BrowserError("Brave didn't answer in time") from e
    if out.returncode != 0:
        err = out.stderr.strip()
        if "Allow JavaScript from Apple Events" in err or "turned off" in err:
            raise BrowserScriptingOff(ENABLE_INSTRUCTIONS)
        raise BrowserError(f"Brave scripting failed: {err[:300]}")
    return out.stdout.strip()


_SNAPSHOT_JS = r"""
(() => {
  const MAX = %d;
  const vw = innerWidth, vh = innerHeight;
  const sel = 'a[href],button,input,textarea,select,[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=option],[role=combobox],[role=switch],[contenteditable=true],summary';
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const labelOf = el => {
    let t = el.getAttribute('aria-label');
    if (t) return clean(t);
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) return clean(l.innerText); }
    const wrap = el.closest('label'); if (wrap) { t = clean(wrap.innerText); if (t) return t; }
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { t = clean(lb.split(' ').map(i => (document.getElementById(i) || {}).innerText || '').join(' ')); if (t) return t; }
    if (el.placeholder) return clean(el.placeholder);
    t = clean(el.innerText || el.value || el.title || el.alt || '');
    if (t) return t;
    const img = el.querySelector && el.querySelector('img[alt]'); return img ? clean(img.alt) : '';
  };
  const roleOf = el => {
    const r = el.getAttribute('role'); if (r) return r;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'select') return 'dropdown';
    if (tag === 'textarea' || el.isContentEditable) return 'text area';
    if (tag === 'input') {
      const ty = (el.type || 'text').toLowerCase();
      if (['checkbox','radio'].includes(ty)) return ty;
      if (['button','submit','reset','image'].includes(ty)) return 'button';
      return ty === 'password' ? 'password field' : 'text field';
    }
    return tag === 'summary' ? 'disclosure' : tag;
  };
  const pos = r => {
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const v = cy < vh / 3 ? 'upper' : cy < 2 * vh / 3 ? 'middle' : 'lower';
    const h = cx < vw / 3 ? 'left' : cx < 2 * vw / 3 ? 'center' : 'right';
    return cy < 0 ? 'above view' : cy > vh ? 'below view' : v + ' ' + h;
  };
  document.querySelectorAll('[data-eddy-id]').forEach(e => e.removeAttribute('data-eddy-id'));
  const out = [];
  let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (out.length >= MAX) break;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || el.type === 'hidden') continue;
    if (r.bottom < -vh || r.top > 2 * vh) continue;
    const id = 'p' + (n++);
    el.setAttribute('data-eddy-id', id);
    const tag = el.tagName.toLowerCase();
    const editable = (tag === 'input' && !['checkbox','radio','button','submit','reset','image','file'].includes((el.type||'').toLowerCase())) || tag === 'textarea' || el.isContentEditable;
    const secure = tag === 'input' && (el.type || '').toLowerCase() === 'password';
    out.push({
      id, tag, role: roleOf(el), label: labelOf(el).slice(0, 120),
      value: secure ? '' : clean(tag === 'select' ? (el.selectedOptions[0] || {}).text : (el.isContentEditable ? el.innerText : el.value)).slice(0, 120),
      placeholder: clean(el.placeholder).slice(0, 80),
      editable, enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
      checked: ('checked' in el && ['checkbox','radio'].includes((el.type||'').toLowerCase())) ? !!el.checked : (el.getAttribute('aria-checked') ? el.getAttribute('aria-checked') === 'true' : null),
      focused: document.activeElement === el, secure, position: pos(r),
      in_view: r.bottom > 0 && r.top < vh,
    });
  }
  const text = [];
  for (const h of document.querySelectorAll('h1,h2,h3,[role=heading],[role=alert],.error,[aria-live]')) {
    const r = h.getBoundingClientRect(); const t = clean(h.innerText);
    if (t && r.bottom > 0 && r.top < vh && text.length < 25) text.push(t.slice(0, 140));
  }
  return JSON.stringify({url: location.href, title: document.title, elements: out, text});
})()
""" % MAX_PAGE_ELEMENTS


def snapshot() -> PageSnapshot:
    raw = _run_js(_SNAPSHOT_JS)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BrowserError(f"couldn't read the page: {raw[:200]!r}") from e
    return PageSnapshot(
        url=data.get("url", ""),
        title=data.get("title", ""),
        elements=[PageElement(**e) for e in data.get("elements", [])],
        text=data.get("text", []),
    )


def _act(js_body: str, element_id: str) -> str:
    js = (
        "(() => { const el = document.querySelector('[data-eddy-id=\"%s\"]');"
        " if (!el) return 'MISSING';"
        " el.scrollIntoView({block: 'center'}); %s })()"
    ) % (element_id.replace('"', ""), js_body)
    result = _run_js(js)
    if result == "MISSING":
        raise BrowserError(f"element {element_id} is no longer on the page (it re-rendered) — look again")
    return result


def click(element_id: str) -> str:
    _act("el.focus(); el.click(); return 'ok';", element_id)
    return f"clicked {element_id}"


def fill(element_id: str, text: str) -> str:
    payload = json.dumps(text)
    body = (
        "if (el.type === 'password') return 'SECURE';"
        " el.focus();"
        f" const v = {payload};"
        " if (el.isContentEditable) { el.innerText = v; }"
        " else if (el.tagName === 'SELECT') {"
        "   const o = [...el.options].find(o => o.text.trim().toLowerCase() === v.trim().toLowerCase() || o.value === v);"
        "   if (!o) return 'NOOPTION'; el.value = o.value; }"
        " else { const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
        "   Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v); }"
        " el.dispatchEvent(new Event('input', {bubbles: true}));"
        " el.dispatchEvent(new Event('change', {bubbles: true}));"
        " return 'ok';"
    )
    result = _act(body, element_id)
    if result == "SECURE":
        raise BrowserError("refusing to type into a password field")
    if result == "NOOPTION":
        raise BrowserError(f"that dropdown has no option matching {text!r}")
    return f"filled {element_id} ({len(text)} chars)"


def scroll(direction: str) -> str:
    _run_js("window.scrollBy(0, %d * innerHeight * 0.8); 'ok'" % (1 if direction == "down" else -1))
    return f"scrolled page {direction}"
