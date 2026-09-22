# Project Skills — Sonali Nayak (techwarq)

One file per shipped project: **what** it is, **why** it exists, **how** it was built, plus copy-paste lines for job forms. Sources: GitHub API (`techwarq/*`, Sep 2026) + live sites (usesnips.com, talo.abstraklabs.com) + npm (`@techwarq/ailens`).

| File | Project | Stack | Status |
|---|---|---|---|
| `allore.md` | Allore — AI brand-storytelling backend | TS, Hono, Cloudflare Workers, Drizzle, Qdrant | Shipped BE + waitlist |
| `snips.md` | Snips AI — papers explained simply | Web app (usesnips.com) | Live, beta users |
| `agent-api.md` | Goal-to-agent backend platform | TS, Hono, Workers, D1, Dodo | Phased, verified live |
| `abstrak-talo.md` | Talo site — AI freelancer $10/hr | Next.js, React, Tailwind | Live, waitlist 50% off |
| `ai-lens.md` | LLM observability SDK+CLI | TS, zero deps, npm MIT | Published |
| `flowdesk.md` | Multi-account browser automation desktop app | Electron, React, Fastify, Playwright | Built Jan 2026 |
| `edith.md` | Personal AI agent | Python FastAPI, Qwen, Qdrant, Temporal | Active (this repo) |

Related but not yet filed: `linkedin_scraper` (JS), `tax-doc-checklist` (Python/FastAPI IRS-forms tool), `ai_order_supervisor`, `LookOut.Ai`, `Auto.io` — say the word and I'll file them too.

## How Edith uses these
- **Job forms:** ask in chat ("fill this Senior Full-Stack application using my projects") — Edith reads these files + `resume_profile` and drafts grounded answers. Nothing invented.
- **Content:** each project is also saved as a `proof` skill for `urn:li:person:ncCpvcC0Ax` / `x:TeenCode6`, so the LinkedIn/X grower pulls real proof points automatically.
- **Keep fresh:** after shipping something new, tell Edith and she'll update the file + memory.
