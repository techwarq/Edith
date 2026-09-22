# FlowDesk — Desktop App for Multi-Account Browser Automation

Repo: `techwarq/Final_Flowdesk` (evolved from `techwarq/flowdesk`) · TypeScript · Jan 2026

## What I built
FlowDesk, a desktop application (React + Vite + Tailwind UI packaged with Electron) backed by a Fastify automation server: operate many web accounts and repetitive portal workflows from one place, with isolated browser profiles, fingerprints, cookies, and sessions — plus order/batch workflows and email intake.

## Why I built it
Teams running outreach, ops, or order flows juggle dozens of logins across browsers and/G incognito windows; sessions leak into each other, logins die, and repetitive portal work eats hours. FlowDesk gives every account its own isolated, resumable browser identity with automation on top.

## How I built it
- **Desktop UI** (`src-ui/`): React + Vite + Tailwind — App, Dashboard, UserDashboard, pages, hooks, typed API layer.
- **Automation backend** (`backend/`, Fastify): `browserManager` + Playwright/Playwright-core + Stagehand + Browserbase SDK for scripted browsing; per-profile `fingerprint`, `cookies`, `localStorage`, `session` isolation; `accounts`/`profiles` management with bcrypt auth (Supabase + local).
- **Email intake:** `imap-simple` + `mailparser` pipeline (`email.ts`) for reading operational mail into workflows.
- **Data:** Supabase client + local SQLite schema (`local_storage_schema.sql`) + `vector_store.ts` for semantic recall over stored content.
- **Ops:** `orders`/`batchOrders` workflows, `refresh`/`cloud` sync paths, `crypto` helpers, Winston logging, Zod validation, Commander CLI entry points, Electron-builder packaging.

## Proof
- Full-stack desktop + server codebase: isolated-profile automation, email-to-workflow intake, and batched order runs in one system.

## For job forms (copy-paste)
- **One-liner:** Built a desktop + server system (Electron/React/Fastify/TypeScript) for multi-account browser automation with isolated fingerprints, sessions, and email-driven workflows.
- **Bullets:**
  - Implemented per-profile browser isolation (fingerprint, cookies, storage, sessions) over Playwright/Stagehand/Browserbase.
  - Built an email-intake pipeline (IMAP + parsing) feeding automation workflows, plus batched order processing.
  - Shipped React dashboard UI with typed API layer, Supabase auth, and packaged desktop distribution.
- **Hardest problem:** session isolation at scale — keeping dozens of accounts logged in without cross-contamination, solved with strict per-profile storage/fingerprint boundaries.
