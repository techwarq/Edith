# agent-api — Goal-to-Autonomous-Agent Backend Platform

Repo: `techwarq/agent-api` · TypeScript · Sep 2026

## What I built
A Cloudflare Workers backend that turns natural-language **goals into autonomous agents**: auth, a tool/skill registry, a goal→checklist builder with deterministic pricing, and payments — the full spine for shipping agents without per-vendor glue code. Developed in tracked phases with a `BUILD_LOG.md`; every phase verified live.

## Why I built it
Agent demos are easy; production agents need auth, real tool manifests, bounded planning, pricing, and payments — rebuilt from scratch every time. This is that foundation, once, with receipts per phase.

## How I built it
- **Foundation:** Hono + TypeScript on Workers (`nodejs_compat`), D1 (`agents-db`), generic `createRepository<T>()` factory used by every table.
- **Auth** (`src/auth/`): JWT access tokens via `jose` (HS256, 15 min) + opaque rotating SHA-256-hashed refresh tokens (30d, single-use); passwords hashed with Web Crypto PBKDF2 (100k iterations, zero extra deps).
- **LLM** (`src/llm/openrouter.ts`): one OpenRouter client — switching providers is just a different model string, no per-vendor code.
- **Registry** (`src/registry/`): tools (`web_search` via OpenRouter `:online` suffix so no separate search key, `http_fetch`) and skills (`react_loop`, `planning`, `checkpointing`, `human_approval_gate`, each a real `createBehavior()`), with public manifest endpoints the builder can only recommend from — the LLM can never invent a tool id.
- **Builder1** (`src/builder/`): goal → capped 3-round clarification loop → structured checklist; a deterministic pricing rubric (tool count + repetition + risk multiplier) **clamps** the LLM's hour estimate instead of trusting it.
- **Payments** (`src/payments/`): Dodo integration with HMAC-SHA256 webhook verification (constant-time compare, 5-min replay tolerance), unit-tested against valid/tampered/stale vectors, fails closed. Generic `createStateMachine()` factory shared with future agent runs.

## Proof
- Phase-by-phase build log with live verifications (register/409-duplicate/login/401/refresh-rotation, registry manifests, builder pipeline, webhook signature vectors).

## For job forms (copy-paste)
- **One-liner:** Built a serverless backend platform (Cloudflare Workers/Hono/TypeScript) that converts natural-language goals into autonomous agents with auth, tool registry, priced build plans, and payments.
- **Bullets:**
  - Implemented JWT + rotating-refresh auth and a generic repository factory over D1.
  - Built a tool/skill registry with behavior-level skills (ReAct loop, planning, checkpointing, human approval) and a builder that grounds LLM plans in real manifests.
  - Added deterministic pricing clamps over LLM estimates and unit-tested HMAC webhook verification for payments.
- **Hardest problem:** constraining LLM output to reality — solved with manifest-grounded generation plus a deterministic rubric that overrides the model's own estimates.
