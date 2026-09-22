# Edith — Personal AI Agent (Memory + Voice + Autonomous Jobs)

Repo: `techwarq/Edith` · Python (FastAPI) + TypeScript dashboards · Jul 2026 – present

## What I built
Edith, a personal AI agent that builds a long-term working relationship with one user: remembers facts, recalls conversations semantically, talks (STT/TTS), acts on Google Workspace + WhatsApp, runs scheduled autonomous jobs (Temporal), and ships with an Android app, an Electron desktop island, and a Next.js dashboard. This session's LinkedIn growth engine (OAuth autopost, Qwen content planner, daily viral queue, week plans) is part of it.

## Why I built it
Generic assistants start every session from zero — the same memory problem I write about. Edith keeps durable memory (facts, vectors, history) and takes autonomous action on schedules, so "remind me / apply for me / post for me" actually happens.

## How I built it
- **Core loop:** FastAPI + SSE; OpenRouter tool-calling loop (Qwen, 8-iteration cap, retry/backoff, context-trim fallback); Gemini native grounding + embeddings; tool registry with pure text-in/out contract.
- **Memory:** SQLite (facts, sessions, FTS5 history) + Qdrant semantic vectors (Gemini embeddings) + optional pgvector; nightly reflection + eval jobs.
- **Integrations:** Gmail/Drive/Calendar/Docs/Sheets, WhatsApp (Playwright + Browserbase), Health Connect, Firebase push, Hunter.io enrichment, Vercel/Dodo/GitHub monitor panels, Monid third-party endpoints.
- **Scheduling:** Temporal Cloud workflows (nightly reflection, job-search pipeline with daily caps, deep-research runs).
- **Clients:** `edith-android` (Capacitor), `edith-desktop` (Electron Dynamic Island + dashboard window), `edith-dashboard` (Next.js observability UI), `edith/web` (hosted PWA UI with Chat/Monitor/Goals/Jobs/**Content** tabs).
- **Growth engine:** LinkedIn OAuth 2.0 + Posts/Images API autopost, Qwen planner with per-author voice/goals/skills, GitHub-digest-grounded daily queue, 7-day Talo arcs.

## Proof
- Multi-client monorepo with Docker + Railway deploy, test suite, and a live autonomous content pipeline (generate → schedule → publish → stats → learn).

## For job forms (copy-paste)
- **One-liner:** Built a full-stack personal AI agent (Python/FastAPI, TypeScript clients) with durable memory, voice, third-party integrations, and autonomous scheduled jobs.
- **Bullets:**
  - Implemented an LLM tool-calling loop with capped iterations, retry/backoff, and multi-tier memory (SQLite FTS5 + Qdrant vectors + nightly reflection).
  - Integrated Gmail/Drive/Calendar, WhatsApp, Temporal schedules, push notifications, and three client apps (Android, Electron, Next.js).
  - Built a LinkedIn content autopilot: OAuth, media upload, scheduling worker, stats-driven learning loop.
- **Hardest problem:** reliability of long-horizon autonomy — solved with pending-action approval gates, idempotent schedules, eval harnesses, and graceful degradation when any integration is unconfigured.
