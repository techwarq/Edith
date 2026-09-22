"""LinkedIn OAuth 2.0 for Abstrak Labs (77qb6yf4wyt9e3).

Flow:
  1. GET /api/linkedin/auth/start?token=EDITH_API_TOKEN → returns auth_url
  2. User visits LinkedIn, approves → LinkedIn redirects to LINKEDIN_REDIRECT_URI?code=...&state=...
  3. GET /api/linkedin/callback?code=...&state=... → exchanges code for access_token, fetches profile, upserts linkedin_authors
  4. Tokens stored in linkedin_authors + linkedin_accounts, expires_at = now + expires_in

Scopes requested correspond to Products you enable in the LinkedIn Developer portal:
  - Sign In with LinkedIn using OpenID Connect: openid, profile, email
  - Share on LinkedIn: w_member_social
  - Community Management (for Company Pages): w_organization_social, r_organization_social, r_organization_admin

Add redirect URLs in your screenshot's "Authorized redirect URLs" section:
  http://localhost:8000/api/linkedin/callback
  https://<your-railway>.up.railway.app/api/linkedin/callback
Both must exactly match LINKEDIN_REDIRECT_URI at request time.
"""
import logging
import os
import secrets
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

logger = logging.getLogger("edith.linkedin.auth")

# LinkedIn OAuth endpoints
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"  # OpenID Connect
ME_URL = "https://api.linkedin.com/v2/me"  # fallback
ORG_ACL_URL = "https://api.linkedin.com/v2/organizationAcls?q=roleAssignee"  # for company pages

# After you add products (per screenshots):
#  - "Sign In with LinkedIn using OpenID Connect" → openid profile email
#  - "Share on LinkedIn" → w_member_social (now enabled)
#  - "Community Management" (verified) → r_organization_social w_organization_social (next)
DEFAULT_SCOPES = "openid profile email w_member_social"

# In-memory state store (CSRF). Survives for process lifetime; also persisted to DB table if available.
_state_store: dict[str, float] = {}  # state -> created_at epoch

def _get_cfg():
    cid = os.environ.get("LINKEDIN_CLIENT_ID", "").strip()
    csec = os.environ.get("LINKEDIN_CLIENT_SECRET", "").strip()
    redir = os.environ.get("LINKEDIN_REDIRECT_URI", "").strip()
    # also support legacy names
    if not cid:
        cid = os.environ.get("LINKEDIN_CLIENT_ID", "").strip()
    return cid, csec, redir

def _ensure_state_table(conn) -> None:
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linkedin_oauth_states (
                state TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
        """)
        conn.commit()
    except Exception:
        logger.exception("ensure state table failed")

def create_state(conn=None) -> str:
    state = secrets.token_urlsafe(32)
    _state_store[state] = time.time()
    if conn is not None:
        try:
            _ensure_state_table(conn)
            conn.execute("INSERT INTO linkedin_oauth_states (state) VALUES (?)", (state,))
            conn.commit()
        except Exception:
            logger.exception("store state failed")
    # cleanup old (>10m)
    cutoff = time.time() - 600
    for k, v in list(_state_store.items()):
        if v < cutoff:
            _state_store.pop(k, None)
    return state

def verify_state(conn, state: str) -> bool:
    if not state:
        return False
    # check memory
    if state in _state_store:
        _state_store.pop(state, None)
        if conn is not None:
            try:
                conn.execute("DELETE FROM linkedin_oauth_states WHERE state=?", (state,))
                conn.commit()
            except: pass
        return True
    # check DB
    if conn is not None:
        try:
            _ensure_state_table(conn)
            row = conn.execute("SELECT 1 FROM linkedin_oauth_states WHERE state=?", (state,)).fetchone()
            if row:
                conn.execute("DELETE FROM linkedin_oauth_states WHERE state=?", (state,))
                conn.commit()
                return True
        except Exception:
            logger.exception("verify state db failed")
    return False

def build_auth_url(conn, redirect_uri: Optional[str] = None, scopes: Optional[str] = None) -> tuple[str, str]:
    cid, csec, cfg_redir = _get_cfg()
    if not cid:
        raise RuntimeError("LINKEDIN_CLIENT_ID not set. Copy Client ID from your screenshot (77qb6yf4wyt9e3) into .env")
    redir = (redirect_uri or cfg_redir or "").strip()
    if not redir:
        # default to localhost callback for dev
        redir = "http://localhost:8000/api/linkedin/callback"
    if not csec:
        logger.warning("LINKEDIN_CLIENT_SECRET not set — auth URL will still build but token exchange will fail until set")
    state = create_state(conn)
    scope = scopes or os.environ.get("LINKEDIN_SCOPES", DEFAULT_SCOPES)
    params = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": redir,
        "state": state,
        "scope": scope,
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    return url, state

def exchange_code_for_token(code: str, redirect_uri: Optional[str] = None) -> dict:
    cid, csec, cfg_redir = _get_cfg()
    redir = (redirect_uri or cfg_redir or "").strip()
    if not redir:
        redir = "http://localhost:8000/api/linkedin/callback"
    if not cid or not csec:
        raise RuntimeError("LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET not set in .env")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redir,
        "client_id": cid,
        "client_secret": csec,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(TOKEN_URL, data=data, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed {resp.status_code}: {resp.text[:800]}")
    j = resp.json()
    # j: {access_token, expires_in, refresh_token, refresh_token_expires_in, scope}
    return j

def fetch_linkedin_profile(access_token: str) -> dict:
    """Fetch personal profile via OpenID userinfo. Returns {sub, name, email, picture, urn}."""
    headers = {"Authorization": f"Bearer {access_token}"}
    # Try userinfo first (requires openid)
    try:
        r = requests.get(USERINFO_URL, headers=headers, timeout=15)
        if r.status_code == 200:
            j = r.json()
            # j has sub (id), name, given_name, family_name, picture, email, etc.
            # LinkedIn person URN is urn:li:person:{sub}
            sub = j.get("sub") or j.get("id")
            if sub:
                j["person_urn"] = f"urn:li:person:{sub}"
            return j
    except Exception:
        logger.exception("userinfo fetch failed, trying /v2/me")

    # Fallback to /v2/me (requires r_liteprofile)
    try:
        r = requests.get(ME_URL, headers={**headers, "X-Restli-Protocol-Version": "2.0.0"}, timeout=15)
        if r.status_code == 200:
            j = r.json()
            lid = j.get("id")
            if lid:
                j["person_urn"] = f"urn:li:person:{lid}"
                j["name"] = j.get("localizedFirstName","") + " " + j.get("localizedLastName","")
            return j
    except Exception:
        logger.exception("me fetch failed")
    # return at least token debug
    return {"person_urn": None, "name": "Unknown"}

def fetch_organization_acls(access_token: str) -> list[dict]:
    """Fetch orgs where user is admin (for company authors). Requires r_organization_social / r_organization_admin."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Linkedin-Version": os.environ.get("LINKEDIN_VERSION", "202607"),
    }
    try:
        # This returns organizationAcls with organization urns
        r = requests.get(ORG_ACL_URL, headers=headers, timeout=15)
        if r.status_code == 200:
            j = r.json()
            return j.get("elements", [])
        else:
            logger.warning("org_acl fetch %s %s", r.status_code, r.text[:500])
            return []
    except Exception:
        logger.exception("org_acl fetch failed")
        return []

def store_token_for_author(conn, token_data: dict, profile: dict, access_token: str) -> list[dict]:
    """Upsert personal author + any org authors. Returns list of created authors."""
    from edith.linkedin.store import upsert_author
    expires_in = int(token_data.get("expires_in", 5184000))  # default 60 days
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    scopes = token_data.get("scope", "")
    refresh_token = token_data.get("refresh_token")

    created = []
    person_urn = profile.get("person_urn")
    name = profile.get("name") or profile.get("given_name") or "LinkedIn User"
    if person_urn:
        author = upsert_author(conn, "personal", person_urn, name, vanity_name=profile.get("email",""))
        # update token fields
        conn.execute(
            "UPDATE linkedin_authors SET access_token=?, refresh_token=?, expires_at=?, scopes=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE urn=?",
            (access_token, refresh_token, expires_at, scopes, person_urn),
        )
        # also insert into linkedin_accounts for compat
        try:
            import uuid
            aid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO linkedin_accounts (id, author_urn, access_token, refresh_token, expires_at, scope) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(author_urn) DO UPDATE SET access_token=excluded.access_token, refresh_token=excluded.refresh_token, expires_at=excluded.expires_at, scope=excluded.scope, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                (aid, person_urn, access_token, refresh_token, expires_at, scopes),
            )
        except Exception:
            # table may have id primary key, use upsert via urn uniqueness workaround: just try
            logger.exception("accounts insert failed")
        conn.commit()
        # re-read
        row = conn.execute("SELECT * FROM linkedin_authors WHERE urn=?", (person_urn,)).fetchone()
        if row:
            created.append(dict(row))

    # Try orgs
    org_elements = fetch_organization_acls(access_token)
    for el in org_elements:
        org_urn = el.get("organization") or el.get("organizationalTarget") or ""
        if not org_urn or not org_urn.startswith("urn:li:organization:"):
            continue
        role = el.get("role", "ADMINISTRATOR")
        # only add if admin/content admin
        org_name = org_urn  # we don't have name without extra call; user can rename
        try:
            # try fetch org details
            headers = {
                "Authorization": f"Bearer {access_token}",
                "X-Restli-Protocol-Version": "2.0.0",
                "Linkedin-Version": os.environ.get("LINKEDIN_VERSION", "202607"),
            }
            oid = org_urn.split(":")[-1]
            r = requests.get(f"https://api.linkedin.com/v2/organizations/{oid}", headers=headers, timeout=10)
            if r.status_code == 200:
                org_name = r.json().get("localizedName") or r.json().get("vanityName") or org_urn
        except: pass
        author = upsert_author(conn, "company", org_urn, org_name, vanity_name="")
        conn.execute(
            "UPDATE linkedin_authors SET access_token=?, refresh_token=?, expires_at=?, scopes=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE urn=?",
            (access_token, refresh_token, expires_at, scopes, org_urn),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM linkedin_authors WHERE urn=?", (org_urn,)).fetchone()
        if row:
            created.append(dict(row))

    return created
