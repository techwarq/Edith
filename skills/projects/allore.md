# Allore — AI Brand-Storytelling Backend

Repo: `techwarq/allore-be` (+ `techwarq/waitlist.allore` landing page) · TypeScript · Apr 2026 – Aug 2026

## What I built
Backend for Allore AI, a platform on the belief that **brands that tell stories win**. It turns a user's plain-English request into on-brand creative output — ads, AI photoshoots, social posts, visuals — every asset tied to a deeper brand narrative, not a one-off image prompt. Includes auth, chat, project/shoot management, Pinterest connector, user memory, feedback loop, waitlist, and billing.

## Why I built it
Generic AI image tools don't understand brand narrative — D2C/fashion brands need consistent, story-driven creative at scale, and a chat box that just generates pictures can't hold a brand voice across a campaign.

## How I built it
- **Runtime:** Cloudflare Workers (`nodejs_compat`) + **Hono** + TypeScript, deployed with Wrangler. Drizzle ORM + Neon Postgres, Qdrant for vector memory.
- **Intent Engine** (`src/core/orchestrator/IntentEngine.ts`): analyzes each message in stages — surface request → deep intent → story layer → minimal logical tool plan — assembled via a `PromptBuilder` over a `ToolCatalog`. Fixed a real divergence bug where the branch copy was missing the `HANDOFF_RULES` export (`tsc` clean after).
- **Skill manifests:** per-tool `*.md` files with `whenToUse`/`routingNotes` frontmatter + prompt body, parsed by `loadSkill.ts` — routing knowledge lives in versioned markdown, not code.
- **Agents:** `PhotoshootAgent`, `PlannerIntentAgent`; `Orchestrator` pipeline + `SimpleShootEngine` + shoot planner (`src/core/{agents,orchestrator,skills,tools,memory,connectors}`).
- **Memory:** `mem_v3` schema (chat_messages, feedback tables) + Qdrant-backed recall so the brand voice persists across sessions.
- **Auth/billing:** Arctic + Jose auth, Dodo Payments billing, Resend emails, Standard Webhooks verification, Zod validation everywhere.
- **Connectors:** Playwright + Stagehand browser automation, Pinterest API integration, Python `garment_preprocessor.py` for fashion-asset prep.
- **API surface** (`src/routes/`): assets, auth, billing, chat, chatV1, creative, feedback, memory, pinterest, profile, project, shoots, storytelling, suggestions, user, waitlist. Durable Objects for stateful runs.

## Proof
- Working backend with phased delivery (Orchestrator → shoot engine → memory v3 → billing), waitlist landing page live.

## For job forms (copy-paste)
- **One-liner:** Built the backend for an AI brand-storytelling platform (Cloudflare Workers/Hono/TypeScript) with an intent-routing engine, creative agents, and persistent brand memory.
- **Bullets:**
  - Designed an Intent Engine that decomposes surface requests into deep intent + story layer + minimal tool plans, with routing rules stored as versioned skill manifests.
  - Built Photoshoot/Planner agents, an orchestrator pipeline, and a Qdrant-backed memory schema so brand voice persists across sessions.
  - Shipped auth, chat, billing (Dodo), Pinterest + browser connectors, and 16 REST route modules on serverless infra.
- **Hardest problem:** keeping a multi-branch prompt/skill system consistent — caught a missing `HANDOFF_RULES` export that silently broke handoffs and fixed it to a clean `tsc` build.
