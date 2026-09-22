"""LinkedIn Posts/Images API — publish + stats.

Uses stored access_token from linkedin_authors. Handles both personal (urn:li:person:) and
company (urn:li:organization:) if caller has w_organization_social.

Docs: POST https://api.linkedin.com/rest/posts  +  POST https://api.linkedin.com/rest/images
Headers required: Linkedin-Version, X-Restli-Protocol-Version, Authorization
"""
import base64
import logging
import os
import time
import requests
from typing import Optional

logger = logging.getLogger("edith.integrations.linkedin.client")

LINKEDIN_VERSION = os.environ.get("LINKEDIN_VERSION", "202607")
POSTS_URL = "https://api.linkedin.com/rest/posts"
IMAGES_URL = "https://api.linkedin.com/rest/images"
SOCIAL_META_URL = "https://api.linkedin.com/rest/socialMetadata"

def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Linkedin-Version": os.environ.get("LINKEDIN_VERSION", LINKEDIN_VERSION),
        "Content-Type": "application/json",
    }

def get_access_token(conn, author_urn: str) -> str:
    row = conn.execute("SELECT access_token, expires_at FROM linkedin_authors WHERE urn=?", (author_urn,)).fetchone()
    if not row or not row["access_token"]:
        raise RuntimeError(f"No access_token for {author_urn} — re-auth via /api/linkedin/auth/start")
    # optionally check expiry
    return row["access_token"]

def register_image(conn, author_urn: str, image_b64: str) -> str:
    """Uploads image, returns urn:li:image:... . Two-step: initializeUpload -> PUT uploadUrl -> image urn."""
    if not image_b64:
        raise ValueError("image_b64 empty")
    access_token = get_access_token(conn, author_urn)
    # decode to bytes to know size, but we send via uploadUrl PUT
    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception as e:
        raise RuntimeError(f"invalid base64 image: {e}")
    # Step 1: initializeUpload
    init_payload = {
        "initializeUploadRequest": {
            "owner": author_urn,
        }
    }
    headers = _headers(access_token)
    resp = requests.post(IMAGES_URL, headers=headers, json=init_payload, timeout=20)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Image init failed {resp.status_code}: {resp.text[:800]}")
    j = resp.json()
    # j = {value: {uploadUrl, image, uploadUrlExpiresAt}}
    value = j.get("value") or j
    upload_url = value.get("uploadUrl")
    image_urn = value.get("image")  # urn:li:image:...
    if not upload_url or not image_urn:
        raise RuntimeError(f"Unexpected image init response: {j}")
    # Step 2: PUT bytes to uploadUrl
    put_headers = {"Authorization": f"Bearer {access_token}"}
    # uploadUrl is pre-signed, may not need auth? But docs say include auth. Try with.
    put_resp = requests.put(upload_url, data=image_bytes, headers={"Content-Type": "application/octet-stream"}, timeout=30)
    if put_resp.status_code not in (200, 201, 204):
        # try with auth header
        put_resp = requests.put(upload_url, data=image_bytes, headers={**put_headers, "Content-Type": "application/octet-stream"}, timeout=30)
        if put_resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"Image upload PUT failed {put_resp.status_code}: {put_resp.text[:500]}")
    # Poll for availability? LinkedIn images need a short processing time; we just return urn and caller can retry post if needed.
    return image_urn

def create_post(conn, author_urn: str, commentary: str, image_urn: Optional[str] = None, visibility: str = "PUBLIC") -> dict:
    """Creates a post, returns LinkedIn response JSON with id."""
    if not commentary or not commentary.strip():
        raise ValueError("commentary empty")
    if len(commentary) > 3000:
        commentary = commentary[:3000]
    access_token = get_access_token(conn, author_urn)
    headers = _headers(access_token)

    # Build content
    if image_urn:
        # image post
        payload = {
            "author": author_urn,
            "commentary": commentary,
            "visibility": visibility,
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "content": {
                "media": {
                    "id": image_urn,
                }
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
    else:
        payload = {
            "author": author_urn,
            "commentary": commentary,
            "visibility": visibility,
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

    resp = requests.post(POSTS_URL, headers=headers, json=payload, timeout=20)
    if resp.status_code not in (200, 201):
        # try decode error
        raise RuntimeError(f"Posts create failed {resp.status_code}: {resp.text[:1500]}")
    j = resp.json() if resp.content else {}
    # response typically has id = urn:li:share:... or header x-restli-id
    post_id = j.get("id") or resp.headers.get("x-restli-id") or resp.headers.get("X-RestLi-Id") or j.get("urn")
    # also check location header
    if not post_id:
        post_id = j.get("id") or str(j)
    return {"id": post_id, "raw": j, "headers": dict(resp.headers), "payload": payload}

def create_post_for_stored(conn, post_id: str) -> dict:
    """Publish a stored draft/manual post (from linkedin_posts). Handles image upload if present."""
    row = conn.execute("SELECT * FROM linkedin_posts WHERE id=?", (post_id,)).fetchone()
    if not row:
        raise ValueError(f"post not found: {post_id}")
    d = dict(row)
    author_urn = d["author_urn"]
    commentary = d["commentary"]
    image_b64 = d["image_b64"]
    # mark publishing
    conn.execute("UPDATE linkedin_posts SET status='publishing', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (post_id,))
    conn.commit()
    try:
        image_urn = None
        if image_b64:
            image_urn = register_image(conn, author_urn, image_b64)
            # store image_urn
            conn.execute("UPDATE linkedin_posts SET image_urn=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (image_urn, post_id))
            conn.commit()
            # small wait for processing
            time.sleep(1)
        result = create_post(conn, author_urn, commentary, image_urn=image_urn)
        published_urn = result.get("id") or ""
        # LinkedIn post url format
        published_url = ""
        if published_urn and published_urn.startswith("urn:li:share:"):
            # share id
            sid = published_urn.split(":")[-1]
            # For personal, url is linkedin.com/feed/update/urn:li:activity:<id> or share — we store generic
            published_url = f"https://www.linkedin.com/feed/update/{published_urn}"
        elif published_urn and published_urn.startswith("urn:li:ugcPost:"):
            published_url = f"https://www.linkedin.com/feed/update/{published_urn}"
        conn.execute(
            "UPDATE linkedin_posts SET status='published', published_urn=?, published_url=?, published_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'), error=NULL, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (published_urn, published_url, post_id),
        )
        conn.commit()
        return {"post_id": post_id, "published_urn": published_urn, "published_url": published_url, "raw": result["raw"]}
    except Exception as e:
        logger.exception("publish failed for post %s", post_id)
        conn.execute("UPDATE linkedin_posts SET status='failed', error=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (str(e), post_id))
        conn.commit()
        raise

def fetch_post_stats(conn, post_urn: str) -> dict:
    """Fetch socialMetadata for a post urn (requires access_token of author). Best-effort."""
    # Determine author from post_urn? Need to find which author owns post — search linkedin_posts first
    row = conn.execute("SELECT author_urn FROM linkedin_posts WHERE published_urn=?", (post_urn,)).fetchone()
    author_urn = row["author_urn"] if row else None
    if not author_urn:
        # fallback to first personal with token
        row = conn.execute("SELECT urn FROM linkedin_authors WHERE access_token IS NOT NULL LIMIT 1").fetchone()
        author_urn = row["urn"] if row else None
    if not author_urn:
        raise RuntimeError("no author token found for stats")
    access_token = get_access_token(conn, author_urn)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Linkedin-Version": os.environ.get("LINKEDIN_VERSION", LINKEDIN_VERSION),
    }
    # socialMetadata batch? try single
    # post_urn is urn:li:share:... or urn:li:ugcPost:...
    # API expects encoded urn
    import urllib.parse
    encoded = urllib.parse.quote(post_urn, safe="")
    url = f"{SOCIAL_META_URL}/{encoded}"
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"socialMetadata fetch failed {resp.status_code}: {resp.text[:600]}")
    return resp.json()
