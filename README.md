# Edith

A personal AI agent that builds a long-term working relationship with one user — not a
stateless chatbot. Edith remembers facts and conversations, talks (voice in/out), acts on
Gmail/Drive/Calendar and WhatsApp, and runs autonomous scheduled work: nightly self-reflection,
a job-application pipeline that scans VC/accelerator job boards and applies on your behalf, and
a LinkedIn growth engine that plans and posts content. It ships as a hosted API plus four
clients: a PWA, an Android app, an Electron desktop widget, and a native macOS widget.

## Why

Generic assistants start every session from zero. Edith keeps durable memory (facts, semantic
vector recall, full conversation history) and takes autonomous action on a schedule, so
"remind me" / "apply for me" / "post for me" actually happens without being re-explained.

## Architecture

```
edith/
├── server.py          FastAPI app, SSE chat streaming, voice/computer-use endpoints
├── cli.py              Terminal client
├── bootstrap.py         Wires settings + DB + tool registry into one agent context
├── agent.py, commands.py, prompts.py   Core chat/command loop
├── llm/                 OpenRouter tool-calling loop (retry/backoff, context-trim fallback)
├── memory/               SQLite (facts, FTS5 history) + Qdrant/pgvector semantic recall
├── tools/                LLM-callable tools (schema + dispatch), grouped by domain:
│                           growth/ (jobs, outreach, hunter, social), ops/ (github, vercel,
│                           monitor, monid), productivity/ (goals, todos, notes, projects),
│                           search/ (web_search, news, youtube, research), system/ (scheduling,
│                           notify, mcp_client, computer_use)
├── integrations/          Voice (STT/TTS), WhatsApp (Playwright), browser (Browserbase), push
├── google/                Gmail, Drive, Calendar, Docs, Sheets
├── job_applications/       Autonomous job-search & apply pipeline
├── linkedin/               OAuth, content planner, autopost, stats-driven learning loop
├── computer_use/            macOS Accessibility + OCR perception, LLM-driven screen control
├── temporal/                Scheduled/recurring workflows (Temporal Cloud)
├── observability/            Tracing, spend tracking, eval harness
├── goals/, todos/, mcp/, monitor/, web/    Feature APIs + the built-in dashboard UI
└── config.py             Every integration is optional — degrades gracefully if unconfigured

edith-android/    Capacitor Android app
edith-desktop/    Electron "Dynamic Island" voice widget
edith-widget/     Native macOS widget (Swift)
edith-dashboard/  Standalone Next.js observability dashboard
tests/            343 tests, pytest
```

## How it works

- **Core loop** — FastAPI + Server-Sent Events; an OpenRouter tool-calling loop (Qwen) with a
  capped iteration count, retry/backoff, and a context-trim fallback for long tool chains.
- **Memory** — SQLite for facts/sessions/FTS5 history, Qdrant (or pgvector) for semantic vector
  recall, plus a nightly reflection + eval job so the agent's own behavior gets scored over time.
- **Autonomy, gated** — every recurring job (nightly reflection, job-search runs, deep research)
  is opt-in and idempotent via Temporal schedules; anything that sends/submits externally queues
  for user approval until explicitly promoted to autonomous.
- **Observability** — every LLM call and tool call is traced with cost/latency, queryable via
  `/api/observability/*` and the dashboard; caught a real hallucination bug on its first eval run.
- **Integrations** — Gmail/Drive/Calendar/Docs/Sheets, WhatsApp (Playwright + Browserbase),
  Firebase push, Hunter.io enrichment, GitHub/Vercel monitoring, Health Connect, and
  user-configurable MCP servers — each reports "not configured" rather than crashing startup
  when its credentials are absent.

## Running it

```bash
pip install -e .
cp .env.example .env   # fill in the integrations you want
python main.py         # terminal client
# or
uvicorn edith.server:app --reload   # HTTP/SSE API + built-in web dashboard
```

```bash
pytest   # 343 tests
```

Deploys to Railway via the included `Dockerfile`.

## Clients

| Client | Stack | What it's for |
|---|---|---|
| `edith/web` | Vanilla JS PWA, served by the API itself | Chat, Goals, Todos, Jobs, Content, Insights, MCP tabs |
| `edith-android` | Capacitor | Mobile chat + push notifications |
| `edith-desktop` | Electron | Always-on-top notch-hugging voice widget |
| `edith-widget` | Swift | Native macOS equivalent of the Electron widget |
| `edith-dashboard` | Next.js | Standalone observability dashboard (traces, evals, goals) |
