"""FastAPI router for LinkedIn Growth Engine — Phase 2 (best grower agent).

Mounts like goals_api/todos_api. All routes require EDITH_API_TOKEN (same as server.py _unauthorized).
Auth: Bearer via JSON body token field (matches existing /api/* pattern).
"""
import asyncio
import json
import logging
from typing import Any, Optional

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from edith.integrations.linkedin import store as lstore
from edith.integrations.linkedin import pgvector as pgmem
from edith.integrations.linkedin.grower import generate_best_post, save_generated_as_post, generate_calendar_plan
from edith.integrations.linkedin.openrouter import generate_image
from edith.integrations.linkedin.prompts import refine_image_prompt
from edith.integrations.linkedin import auth as linkedin_auth

logger = logging.getLogger("edith.integrations.linkedin.api")

def _unauthorized(body: dict, api_token: str) -> JSONResponse | None:
    if not api_token or body.get("token") != api_token:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None

def build_router(conn, genai_client, api_token: str) -> APIRouter:
    router = APIRouter(prefix="/api/linkedin", tags=["linkedin"])

    # Ensure tables + pgvector on startup
    try:
        lstore.ensure_linkedin_schema(conn)
        pgmem.ensure_pgvector_schema()
    except Exception:
        logger.exception("linkedin ensure schema failed")

    # ---------- authors ----------
    @router.post("/authors")
    async def create_authors(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        # supports single or list
        typ = body.get("type", "company")
        urn = body.get("urn", "").strip()
        name = body.get("name", "").strip()
        vanity = body.get("vanity_name", "").strip()
        if typ not in ("personal", "company"):
            return JSONResponse({"error": "type must be personal|company"}, status_code=400)
        if not urn or not name:
            return JSONResponse({"error": "urn and name required, e.g. urn:li:organization:123 / urn:li:person:abc"}, status_code=400)
        if not urn.startswith("urn:li:"):
            return JSONResponse({"error": "urn must start with urn:li:person: or urn:li:organization:"}, status_code=400)
        def _op():
            return lstore.upsert_author(conn, typ, urn, name, vanity)
        data = await asyncio.to_thread(_op)
        return JSONResponse(data)

    @router.get("/authors")
    async def list_authors(request: Request):
        token = request.query_params.get("token", "")
        if not api_token or token != api_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        def _op():
            return lstore.list_authors(conn)
        data = await asyncio.to_thread(_op)
        return JSONResponse({"authors": data})

    # ---------- goals (per-author) ----------
    @router.post("/goals")
    async def create_goal(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        author_urn = body.get("author_urn", "").strip()
        title = body.get("title", "").strip()
        if not author_urn or not title:
            return JSONResponse({"error": "author_urn and title required"}, status_code=400)
        # validate author exists
        def _op():
            if not lstore.get_author(conn, author_urn):
                return None
            return lstore.create_goal(
                conn,
                author_urn=author_urn,
                title=title,
                description=body.get("description",""),
                target_type=body.get("target_type","growth"),
                target_value=body.get("target_value",""),
                tone=body.get("tone",""),
                pillars=body.get("pillars"),
            )
        data = await asyncio.to_thread(_op)
        if data is None:
            return JSONResponse({"error": f"author not found: {author_urn}"}, status_code=404)
        return JSONResponse(data)

    @router.get("/goals")
    async def get_goals(request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        author_urn = request.query_params.get("author_urn")
        status = request.query_params.get("status","active")
        def _op():
            return lstore.list_goals(conn, author_urn=author_urn, status=status)
        data = await asyncio.to_thread(_op)
        return JSONResponse({"goals": data})

    @router.patch("/goals/{goal_id}")
    async def patch_goal(goal_id: str, request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        def _op():
            return lstore.update_goal(conn, goal_id, **{k:v for k,v in body.items() if k not in ("token")})
        data = await asyncio.to_thread(_op)
        if not data:
            return JSONResponse({"error":"not found"}, status_code=404)
        return JSONResponse(data)

    @router.delete("/goals/{goal_id}")
    async def del_goal(goal_id: str, request: Request):
        body = await request.json() if request.headers.get("content-type","").startswith("application/json") else {}
        # allow token via query for DELETE convenience
        tok = body.get("token") or request.query_params.get("token","")
        if not api_token or tok != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        def _op():
            return lstore.delete_goal(conn, goal_id)
        ok = await asyncio.to_thread(_op)
        if not ok:
            return JSONResponse({"error":"not found"}, status_code=404)
        return JSONResponse({"ok": True})

    # ---------- skills ----------
    @router.post("/skills")
    async def save_skill(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        author_urn = body.get("author_urn","").strip()
        category = body.get("category","content_strategy").strip()
        title = body.get("title","").strip()
        content = body.get("content","").strip()
        if not author_urn or not title or not content:
            return JSONResponse({"error":"author_urn, title, content required"}, status_code=400)
        if category not in ("voice","pillar","audience","offer","proof","content_strategy","style_guide"):
            return JSONResponse({"error":"invalid category"}, status_code=400)
        def _op():
            row = lstore.save_skill(conn, author_urn, category, title, content)
            # also upsert to pgvector for semantic recall (best effort)
            try:
                pgmem.pg_upsert(genai_client, author_urn, category, f"{title}: {content}", pillar=category, metadata={"title": title})
            except Exception:
                logger.exception("pg_upsert skill failed")
            # also keep Qdrant compat via social_skill if you want (optional)
            return row
        data = await asyncio.to_thread(_op)
        return JSONResponse(data)

    @router.get("/skills")
    async def get_skills(request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        author_urn = request.query_params.get("author_urn")
        category = request.query_params.get("category")
        def _op():
            return lstore.list_skills(conn, author_urn=author_urn, category=category)
        data = await asyncio.to_thread(_op)
        return JSONResponse({"skills": data})

    @router.delete("/skills/{skill_id}")
    async def del_skill(skill_id: str, request: Request):
        token = request.query_params.get("token","")
        # also check body
        try:
            body = await request.json()
            token = body.get("token", token)
        except: pass
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        def _op():
            return lstore.delete_skill(conn, skill_id)
        ok = await asyncio.to_thread(_op)
        if not ok:
            return JSONResponse({"error":"not found"}, status_code=404)
        return JSONResponse({"ok": True})

    # ---------- GENERATE — best grower agent ----------
    @router.post("/generate")
    async def generate(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        author_urn = body.get("author_urn","").strip()
        topic = body.get("topic","").strip()
        pillar = body.get("pillar","").strip()
        tone = body.get("tone","").strip()
        goal_id = body.get("goal_id")
        include_image = bool(body.get("include_image", True))
        save = body.get("save", "draft")  # draft|manual|scheduled|none
        scheduled_at = body.get("scheduled_at")  # ISO8601 UTC if scheduled
        if not author_urn or not topic:
            return JSONResponse({"error":"author_urn and topic required"}, status_code=400)
        if save not in ("draft","manual","scheduled","none"):
            return JSONResponse({"error":"save must be draft|manual|scheduled|none"}, status_code=400)

        def _op():
            gen = generate_best_post(conn, genai_client, author_urn, topic, pillar=pillar, tone=tone, goal_id=goal_id, include_image=include_image)
            # persist if requested
            if save != "none":
                # coerce personal scheduled -> manual
                status = save
                post = save_generated_as_post(conn, gen, status=status, scheduled_at=scheduled_at if status=="scheduled" else None)
                # pgvector learn: store commentary for future retrieval
                try:
                    pgmem.pg_upsert(genai_client, author_urn, "post", gen["commentary"], pillar=gen.get("pillar",""), metadata={"post_id": post["id"], "topic": topic})
                except Exception:
                    logger.exception("pg_upsert post failed")
                gen["post_id"] = post["id"]
                gen["status"] = post["status"]
                gen["scheduled_at"] = post.get("scheduled_at")
                # don't leak huge b64 in list view? but return for generate
            return gen

        try:
            data = await asyncio.to_thread(_op)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            logger.exception("generate failed")
            return JSONResponse({"error": str(e)}, status_code=500)
        # strip huge b64 for logging but return
        return JSONResponse(data)

    @router.post("/generate-image")
    async def gen_image(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        prompt = body.get("prompt","").strip() or body.get("image_prompt","").strip()
        author_urn = body.get("author_urn","").strip()
        aspect = body.get("aspect_ratio","1:1")
        if not prompt:
            return JSONResponse({"error":"prompt required"}, status_code=400)
        # optionally refine with persona preset if author given
        if author_urn:
            try:
                a = await asyncio.to_thread(lstore.get_author, conn, author_urn)
                if a:
                    prompt = refine_image_prompt(prompt, a["type"])
            except: pass
        def _op():
            return generate_image(prompt, aspect_ratio=aspect)
        try:
            data = await asyncio.to_thread(_op)
        except Exception as e:
            logger.exception("generate-image failed")
            return JSONResponse({"error": str(e)}, status_code=502)
        return JSONResponse(data)

    @router.post("/plan")
    async def plan(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        author_urn = body.get("author_urn","").strip()
        days = int(body.get("days", 7))
        if not author_urn:
            return JSONResponse({"error":"author_urn required"}, status_code=400)
        days = max(1, min(days, 14))
        def _op():
            return generate_calendar_plan(conn, author_urn, days=days)
        try:
            data = await asyncio.to_thread(_op)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            logger.exception("plan failed")
            return JSONResponse({"error": str(e)}, status_code=500)
        return JSONResponse({"author_urn": author_urn, "days": days, "plan": data})

    # ---------- posts CRUD ----------
    @router.get("/posts")
    async def get_posts(request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        author_urn = request.query_params.get("author_urn")
        status = request.query_params.get("status")
        limit = int(request.query_params.get("limit","50"))
        limit = max(1, min(limit, 100))
        def _op():
            return lstore.list_posts(conn, author_urn=author_urn, status=status, limit=limit)
        data = await asyncio.to_thread(_op)
        # strip b64 for list view to keep payload small
        for d in data:
            if d.get("image_b64"):
                d["has_image"] = True
                d["image_b64"] = d["image_b64"][:100] + "..." if len(d["image_b64"])>100 else d["image_b64"]
        return JSONResponse({"posts": data})

    @router.get("/posts/{post_id}")
    async def get_one(post_id: str, request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        def _op():
            p = lstore.get_post(conn, post_id)
            if not p:
                return None
            stats = lstore.get_stats(conn, post_id, limit=5)
            return {**p, "stats": stats}
        data = await asyncio.to_thread(_op)
        if not data:
            return JSONResponse({"error":"not found"}, status_code=404)
        return JSONResponse(data)

    @router.patch("/posts/{post_id}")
    async def patch_post(post_id: str, request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        body.pop("token", None)
        # allow hashtags as list, scheduled_at, status, commentary etc
        def _op():
            return lstore.update_post(conn, post_id, **body)
        data = await asyncio.to_thread(_op)
        if not data:
            return JSONResponse({"error":"not found"}, status_code=404)
        return JSONResponse(data)

    @router.delete("/posts/{post_id}")
    async def del_post(post_id: str, request: Request):
        token = request.query_params.get("token","")
        try:
            b = await request.json()
            token = b.get("token", token)
        except: pass
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        def _op():
            return lstore.delete_post(conn, post_id)
        ok = await asyncio.to_thread(_op)
        if not ok:
            return JSONResponse({"error":"not found"}, status_code=404)
        return JSONResponse({"ok": True})

    @router.post("/posts/{post_id}/publish")
    async def publish_post(post_id: str, request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        def _op():
            from edith.integrations.linkedin.linkedin_client import create_post_for_stored
            return create_post_for_stored(conn, post_id)
        try:
            result = await asyncio.to_thread(_op)
        except Exception as e:
            logger.exception("publish failed")
            return JSONResponse({"error": str(e)}, status_code=502)
        return JSONResponse(result)

    @router.post("/publish")
    async def publish_direct(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        author_urn = body.get("author_urn","").strip()
        commentary = body.get("commentary","").strip()
        image_b64 = body.get("image_b64")
        if not author_urn or not commentary:
            return JSONResponse({"error":"author_urn and commentary required"}, status_code=400)
        def _op():
            from edith.integrations.linkedin.linkedin_client import get_access_token, register_image, create_post
            # optionally register image
            image_urn = None
            if image_b64:
                image_urn = register_image(conn, author_urn, image_b64)
            res = create_post(conn, author_urn, commentary, image_urn=image_urn)
            # also store as published post for history
            try:
                lstore.create_post(conn, author_urn=author_urn, author_type="personal" if "person:" in author_urn else "company", commentary=commentary, image_b64=image_b64, image_urn=image_urn, status="published", published_urn=res.get("id"), published_url=f"https://www.linkedin.com/feed/update/{res.get('id')}" if res.get("id") else "", model_used="direct")
            except Exception:
                logger.exception("store published post failed")
            return res
        try:
            result = await asyncio.to_thread(_op)
        except Exception as e:
            logger.exception("direct publish failed")
            return JSONResponse({"error": str(e)}, status_code=502)
        return JSONResponse(result)

    # ---------- daily viral queue + shipped digest ----------
    @router.get("/digest")
    async def get_digest(request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        since_days = int(request.query_params.get("since_days","7") or 7)
        since_days = max(1, min(since_days, 30))
        def _op():
            from edith.integrations.linkedin.github_digest import build_digest
            return build_digest(since_days=since_days)
        try:
            data = await asyncio.to_thread(_op)
        except Exception as e:
            logger.exception("digest failed")
            return JSONResponse({"error": str(e)}, status_code=502)
        return JSONResponse(data)

    @router.post("/daily/generate")
    async def daily_generate(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        author_urn = body.get("author_urn","").strip()  # linkedin author urn (personal)
        author_urn_x = body.get("author_urn_x","x:TeenCode6").strip()
        since_days = int(body.get("since_days", 7) or 7)
        if not author_urn:
            return JSONResponse({"error":"author_urn required (your linkedin personal urn)"}, status_code=400)
        def _op():
            from edith.integrations.linkedin.daily import generate_daily_queue
            return generate_daily_queue(conn, author_urn, author_urn_x=author_urn_x, since_days=since_days)
        try:
            data = await asyncio.to_thread(_op)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            logger.exception("daily generate failed")
            return JSONResponse({"error": str(e)}, status_code=500)
        return JSONResponse(data)

    @router.get("/daily")
    async def daily_today(request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        author_urn = request.query_params.get("author_urn")
        def _op():
            from edith.integrations.linkedin.daily import get_todays_queue
            return get_todays_queue(conn, author_urn)
        data = await asyncio.to_thread(_op)
        return JSONResponse({"posts": data})

    @router.post("/week/generate")
    async def week_generate(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        author_urn = body.get("author_urn","").strip()
        author_urn_x = body.get("author_urn_x","x:TeenCode6").strip()
        start_date = body.get("start_date")  # YYYY-MM-DD or None = tomorrow
        if not author_urn:
            return JSONResponse({"error":"author_urn required"}, status_code=400)
        def _op():
            from edith.integrations.linkedin.daily import generate_week_plan
            return generate_week_plan(conn, author_urn, author_urn_x=author_urn_x, start_date=start_date)
        try:
            data = await asyncio.to_thread(_op)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            logger.exception("week generate failed")
            return JSONResponse({"error": str(e)}, status_code=500)
        return JSONResponse(data)

    @router.get("/week")
    async def week_list(request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        author_urn = request.query_params.get("author_urn")
        start = request.query_params.get("start")
        def _op():
            from edith.integrations.linkedin.daily import get_week_plan
            return get_week_plan(conn, author_urn, start=start)
        data = await asyncio.to_thread(_op)
        return JSONResponse({"days": data})

    # ---------- stats + insights ----------
    @router.post("/stats/{post_id}")
    async def add_stat(post_id: str, request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        def _op():
            p = lstore.get_post(conn, post_id)
            if not p:
                return None
            return lstore.add_stat(conn, post_id,
                impressions=int(body.get("impressions",0)),
                members_reached=int(body.get("members_reached",0)),
                reactions=int(body.get("reactions",0)),
                comments=int(body.get("comments",0)),
                reshares=int(body.get("reshares",0)),
                saves=int(body.get("saves",0)),
                sends=int(body.get("sends",0)),
                clicks=int(body.get("clicks",0)),
            )
        data = await asyncio.to_thread(_op)
        if not data:
            return JSONResponse({"error":"post not found"}, status_code=404)
        return JSONResponse(data)

    @router.get("/stats/{post_id}")
    async def get_stats(post_id: str, request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        def _op():
            return lstore.get_stats(conn, post_id)
        data = await asyncio.to_thread(_op)
        return JSONResponse({"stats": data})

    @router.get("/insights")
    async def get_insights(request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        author_urn = request.query_params.get("author_urn")
        def _op():
            return lstore.list_insights(conn, author_urn=author_urn, limit=20)
        data = await asyncio.to_thread(_op)
        return JSONResponse({"insights": data})

    @router.post("/insights")
    async def add_insight(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        author_urn = body.get("author_urn","").strip()
        kind = body.get("kind","recommendation")
        title = body.get("title","").strip()
        body_text = body.get("body","").strip()
        if not author_urn or not title or not body_text:
            return JSONResponse({"error":"author_urn, title, body required"}, status_code=400)
        if kind not in ("winner","loser","pattern","recommendation"):
            return JSONResponse({"error":"kind must be winner|loser|pattern|recommendation"}, status_code=400)
        def _op():
            return lstore.add_insight(conn, author_urn, kind, title, body_text, evidence=body.get("evidence"))
        data = await asyncio.to_thread(_op)
        return JSONResponse(data)

    @router.get("/health")
    async def health(request: Request):
        # no auth needed
        try:
            authors = await asyncio.to_thread(lstore.list_authors, conn)
            posts = await asyncio.to_thread(lstore.list_posts, conn, None, None, 1)
            return JSONResponse({"status":"ok", "authors": len(authors), "pgvector_enabled": pgmem.is_enabled(), "models": {"text":"qwen/qwen3.7-flash","image":"meta/muse-image"}})
        except Exception as e:
            return JSONResponse({"status":"error","error":str(e)}, status_code=500)

    # ---------- OAuth 2.0 ----------
    @router.get("/auth/start")
    async def auth_start(request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized — pass ?token=EDITH_API_TOKEN"}, status_code=401)
        redirect_uri = request.query_params.get("redirect_uri") or request.query_params.get("redirect")
        scopes = request.query_params.get("scopes") or request.query_params.get("scope")
        try:
            def _op():
                return linkedin_auth.build_auth_url(conn, redirect_uri=redirect_uri, scopes=scopes)
            url, state = await asyncio.to_thread(_op)
            return JSONResponse({"auth_url": url, "state": state, "redirect_uri": redirect_uri or "http://localhost:8000/api/linkedin/callback"})
        except Exception as e:
            logger.exception("auth_start failed")
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.post("/auth/start")
    async def auth_start_post(request: Request):
        body = await request.json()
        if (err := _unauthorized(body, api_token)) is not None:
            return err
        redirect_uri = body.get("redirect_uri") or body.get("redirect")
        scopes = body.get("scopes") or body.get("scope")
        try:
            def _op():
                return linkedin_auth.build_auth_url(conn, redirect_uri=redirect_uri, scopes=scopes)
            url, state = await asyncio.to_thread(_op)
            return JSONResponse({"auth_url": url, "state": state, "redirect_uri": redirect_uri or "http://localhost:8000/api/linkedin/callback"})
        except Exception as e:
            logger.exception("auth_start failed")
            return JSONResponse({"error": str(e)}, status_code=500)

    @router.get("/callback")
    async def callback(request: Request):
        # LinkedIn redirects here: ?code=...&state=...
        code = request.query_params.get("code") or ""
        state = request.query_params.get("state") or ""
        error = request.query_params.get("error") or ""
        error_desc = request.query_params.get("error_description") or ""
        if error:
            return JSONResponse({"error": error, "error_description": error_desc}, status_code=400)
        if not code:
            return JSONResponse({"error":"missing code — did LinkedIn redirect without code?"}, status_code=400)
        # verify state CSRF
        ok = await asyncio.to_thread(linkedin_auth.verify_state, conn, state)
        if not ok:
            return JSONResponse({"error":"invalid state — possible CSRF, try /auth/start again"}, status_code=400)
        redirect_uri = request.query_params.get("redirect_uri") or os.environ.get("LINKEDIN_REDIRECT_URI") or "http://localhost:8000/api/linkedin/callback"
        # Determine which redirect_uri was actually used — we stored none, so try the configured one first, fallback to request url base
        # LinkedIn requires exact match, so we try cfg then localhost
        def _op():
            # exchange
            token_data = linkedin_auth.exchange_code_for_token(code, redirect_uri=redirect_uri)
            access_token = token_data.get("access_token")
            if not access_token:
                raise RuntimeError(f"no access_token in response: {token_data}")
            profile = linkedin_auth.fetch_linkedin_profile(access_token)
            authors = linkedin_auth.store_token_for_author(conn, token_data, profile, access_token)
            return {"token_data": {k: v for k,v in token_data.items() if k != "access_token"}, "profile": profile, "authors": authors}
        try:
            result = await asyncio.to_thread(_op)
        except Exception as e:
            logger.exception("callback exchange failed")
            return JSONResponse({"error": str(e)}, status_code=500)
        # For browser flow, return HTML that auto-closes / shows success
        accept = request.headers.get("accept","")
        if "text/html" in accept:
            authors_html = "".join(f"<li>{a['type']}: {a['urn']} — {a['name']}</li>" for a in result["authors"]) or "<li>no author created — check scopes</li>"
            html = f"""<html><body style="font-family:system-ui;padding:32px"><h2>LinkedIn connected ✅</h2><p>Abstrak Labs connected as:</p><ul>{authors_html}</ul><p>You can close this window. Tokens stored in edith.</p><script>setTimeout(()=>window.close(),5000)</script></body></html>"""
            from fastapi.responses import HTMLResponse
            return HTMLResponse(html)
        return JSONResponse(result)

    @router.get("/auth/status")
    async def auth_status(request: Request):
        token = request.query_params.get("token","")
        if not api_token or token != api_token:
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        def _op():
            authors = lstore.list_authors(conn)
            # mask tokens
            for a in authors:
                tok = a.get("access_token")
                if tok:
                    a["has_token"] = True
                    a["access_token"] = tok[:8] + "..." + tok[-4:] if len(tok) > 12 else "***"
                    a["token_expires_at"] = a.get("expires_at")
                else:
                    a["has_token"] = False
            return authors
        data = await asyncio.to_thread(_op)
        return JSONResponse({"authors": data, "redirect_configured": os.environ.get("LINKEDIN_REDIRECT_URI",""), "client_id": os.environ.get("LINKEDIN_CLIENT_ID","")[:8]+"..." if os.environ.get("LINKEDIN_CLIENT_ID") else ""})

    return router
