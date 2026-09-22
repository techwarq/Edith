"""Situation Monitor dashboard tab API — backs the web dashboard's Monitor
tab (edith/web/dashboard.js). Revenue/analytics/shipping panels call a live
external API on each request (no local caching/storage — a personal
dashboard loaded a few times a day doesn't need it) and report
{"configured": false} rather than erroring when their credentials aren't
set, same "optional integration" convention as every other panel in this
codebase. Ideas + Bugs is real CRUD against edith/memory/ideas_bugs_store.py,
since it has no external source. Same shared-token auth pattern as every
other router in the project.
"""

import asyncio
import sqlite3
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from google import genai

from edith.config import Settings
from edith.memory import ideas_bugs_store, store
from edith.monitor import dodo, github_shipping, vercel_analytics
from edith.tools.ops.monitor import SHIPPING_ACCOUNT_CATEGORY, SHIPPING_REPO_CATEGORY, VERCEL_PROJECT_CATEGORY
from edith.tools.search.news import fetch_news
from edith.tools.growth.social import SOCIAL_SKILL_CATEGORY


def build_router(conn: sqlite3.Connection, settings: Settings, genai_client: genai.Client, api_token: str) -> APIRouter:
    router = APIRouter(prefix="/api/monitor", tags=["monitor"])

    def _check_token(token: str) -> Optional[JSONResponse]:
        if not api_token or token != api_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    @router.get("/revenue", response_model=None)
    async def revenue(token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        if not settings.dodo_payments_api_key:
            return JSONResponse({"configured": False})
        try:
            data = await asyncio.to_thread(dodo.get_revenue_summary, settings.dodo_payments_base_url, settings.dodo_payments_api_key)
        except dodo.DodoError as e:
            return JSONResponse({"configured": True, "error": str(e)}, status_code=502)
        return JSONResponse(data)

    def _list_vercel_projects() -> list[dict]:
        facts = store.get_facts_by_category(conn, VERCEL_PROJECT_CATEGORY)
        return [{"project_id": f["key"], "label": f["value"]} for f in facts]

    def _fetch_one_project(project_id: str, label: str, days: int) -> dict:
        try:
            data = vercel_analytics.get_pageview_summary(settings.vercel_analytics_token, project_id, settings.vercel_team_id, days)
            return {"project_id": project_id, "label": label, "pageviews": data["pageviews"], "days": data["days"]}
        except vercel_analytics.VercelAnalyticsError as e:
            return {"project_id": project_id, "label": label, "error": str(e)}

    @router.get("/analytics", response_model=None)
    async def analytics(token: str = "", days: int = 30) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        projects = await asyncio.to_thread(_list_vercel_projects)
        if not (settings.vercel_analytics_token and projects):
            return JSONResponse({"configured": False, "projects": []})
        results = await asyncio.gather(*(asyncio.to_thread(_fetch_one_project, p["project_id"], p["label"], days) for p in projects))
        return JSONResponse({"configured": True, "projects": results})

    @router.post("/analytics/projects", response_model=None)
    async def add_vercel_project(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        project_id = (body.get("project_id") or "").strip()
        if not project_id:
            return JSONResponse({"error": "project_id is required"}, status_code=400)
        label = (body.get("label") or "").strip() or project_id

        def _save() -> None:
            store.save_fact(conn, key=project_id, value=label, category=VERCEL_PROJECT_CATEGORY)

        await asyncio.to_thread(_save)
        return JSONResponse({"project_id": project_id, "label": label})

    @router.post("/analytics/projects/delete", response_model=None)
    async def delete_vercel_project(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        project_id = (body.get("project_id") or "").strip()
        if not project_id:
            return JSONResponse({"error": "project_id is required"}, status_code=400)
        ok = await asyncio.to_thread(store.forget_fact, conn, project_id)
        return JSONResponse({"ok": ok})

    def _list_shipping_repos() -> list[dict]:
        facts = store.get_facts_by_category(conn, SHIPPING_REPO_CATEGORY)
        return [{"repo": f["key"], "label": f["value"]} for f in facts]

    def _list_shipping_accounts() -> list[dict]:
        facts = store.get_facts_by_category(conn, SHIPPING_ACCOUNT_CATEGORY)
        return [{"username": f["key"], "label": f["value"]} for f in facts]

    @router.get("/shipping", response_model=None)
    async def shipping(token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        repos, accounts = await asyncio.gather(asyncio.to_thread(_list_shipping_repos), asyncio.to_thread(_list_shipping_accounts))
        if not repos and not accounts:
            return JSONResponse({"configured": False, "repos": [], "accounts": []})

        commit_lists = await asyncio.gather(
            asyncio.to_thread(github_shipping.get_recent_commits, repos, settings.github_token),
            *(asyncio.to_thread(github_shipping.get_account_activity, a["username"], settings.github_token) for a in accounts),
        )
        commits = [c for batch in commit_lists for c in batch]
        commits.sort(key=lambda c: c.get("date") or "", reverse=True)
        pushes = github_shipping.group_pushes(commits)
        return JSONResponse({"configured": True, "repos": repos, "accounts": accounts, "commits": commits, "pushes": pushes})

    @router.post("/shipping/repos", response_model=None)
    async def add_shipping_repo(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        repo = (body.get("repo") or "").strip()
        if not repo:
            return JSONResponse({"error": "repo is required"}, status_code=400)
        label = (body.get("label") or "").strip() or repo

        def _save() -> None:
            store.save_fact(conn, key=repo, value=label, category=SHIPPING_REPO_CATEGORY)

        await asyncio.to_thread(_save)
        return JSONResponse({"repo": repo, "label": label})

    @router.post("/shipping/repos/delete", response_model=None)
    async def delete_shipping_repo(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        repo = (body.get("repo") or "").strip()
        if not repo:
            return JSONResponse({"error": "repo is required"}, status_code=400)
        ok = await asyncio.to_thread(store.forget_fact, conn, repo)
        return JSONResponse({"ok": ok})

    @router.post("/shipping/accounts", response_model=None)
    async def add_shipping_account(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        username = (body.get("username") or "").strip()
        if not username:
            return JSONResponse({"error": "username is required"}, status_code=400)
        label = (body.get("label") or "").strip() or username

        def _save() -> None:
            store.save_fact(conn, key=username, value=label, category=SHIPPING_ACCOUNT_CATEGORY)

        await asyncio.to_thread(_save)
        return JSONResponse({"username": username, "label": label})

    @router.post("/shipping/accounts/delete", response_model=None)
    async def delete_shipping_account(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        username = (body.get("username") or "").strip()
        if not username:
            return JSONResponse({"error": "username is required"}, status_code=400)
        ok = await asyncio.to_thread(store.forget_fact, conn, username)
        return JSONResponse({"ok": ok})

    @router.get("/news", response_model=None)
    async def news(token: str = "", topic: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        text = await asyncio.to_thread(fetch_news, genai_client, settings.gemini_grounding_model, topic)
        return JSONResponse({"text": text})

    def _social_summary() -> dict:
        content_strategy = store.get_facts_by_category(conn, "content_strategy")
        social_skills = store.get_facts_by_category(conn, SOCIAL_SKILL_CATEGORY)
        return {
            "content_strategy": content_strategy,
            "skills": [{"title": f["key"], "preview": f["value"][:120]} for f in social_skills],
        }

    @router.get("/social", response_model=None)
    async def social(token: str = "") -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        return JSONResponse(await asyncio.to_thread(_social_summary))

    @router.get("/ideas-bugs", response_model=None)
    async def list_ideas_bugs(token: str = "", kind: Optional[str] = None, status: Optional[str] = None) -> JSONResponse:
        if (err := _check_token(token)) is not None:
            return err
        items = await asyncio.to_thread(ideas_bugs_store.list_ideas_bugs, conn, kind, status)
        return JSONResponse({"items": items})

    @router.post("/ideas-bugs", response_model=None)
    async def create_idea_bug(request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        kind = (body.get("kind") or "").strip()
        title = (body.get("title") or "").strip()
        if kind not in ("idea", "bug") or not title:
            return JSONResponse({"error": "kind (idea|bug) and title are required"}, status_code=400)

        def _create() -> dict:
            item_id = ideas_bugs_store.create_idea_bug(conn, kind, title, body.get("note") or None, body.get("project") or None)
            return ideas_bugs_store.get_idea_bug(conn, item_id)

        return JSONResponse(await asyncio.to_thread(_create))

    @router.post("/ideas-bugs/{item_id}/resolve", response_model=None)
    async def resolve_idea_bug(item_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        ok = await asyncio.to_thread(ideas_bugs_store.resolve_idea_bug, conn, item_id)
        if not ok:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(await asyncio.to_thread(ideas_bugs_store.get_idea_bug, conn, item_id))

    @router.post("/ideas-bugs/{item_id}/delete", response_model=None)
    async def delete_idea_bug(item_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        if (err := _check_token(body.get("token", ""))) is not None:
            return err
        ok = await asyncio.to_thread(ideas_bugs_store.delete_idea_bug, conn, item_id)
        return JSONResponse({"ok": ok})

    return router
