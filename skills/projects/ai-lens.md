# ai-lens — Local-First LLM Observability SDK + CLI

Repo: `techwarq/ai-lens` · Package: `@techwarq/ailens` (npm, MIT) · TypeScript, zero runtime deps · May–Jun 2026

## What I built
`ai-lens` brings real software engineering to AI apps: **debug, diff, type-check, and trace your LLM calls**. A 2-line SDK (`lens()`) plus CLI that works with any LLM (OpenAI, Anthropic, Gemini, Groq, Ollama, Mistral, custom). Local-first traces, semantic checks, session diff — zero config.

## Why I built it
You ship an AI feature, something breaks, and you have no idea why: which prompt caused it, whether your last prompt change helped or hurt, whether outputs follow your rules. Normal dev tools don't understand LLM outputs — `ailens` does.

## How I built it
- **SDK** (`src/sdk/`): `lens()` + `tracer.ts` — wrap any LLM call and get structured traces.
- **Analyzers** (`src/analyzers/`): `why` / `trace-why` (root-cause a bad output), `diff` / `semantic-diff` (did this prompt change help?), `causal` (what drove the change), `geval` (rule-following evaluation).
- **Storage** (`src/storage/`): local-first trace store — your prompts never have to leave your machine.
- **CLI** (`src/cli/`) + typed errors + `types.ts`; analysis model is provider-agnostic.
- Published to npm as `@techwarq/ailens` under MIT; README-led docs with problem → 2-line quickstart → SDK/CLI/traces/roadmap.

## Proof
- Public npm package with badges (MIT, local-first, any-LLM); documented quickstart and multi-step pipeline tracing (`<traceName>` fn support).

## For job forms (copy-paste)
- **One-liner:** Built and published an open-source, local-first LLM observability SDK + CLI (TypeScript, zero deps) that traces, diffs, and evaluates prompts across any provider.
- **Bullets:**
  - Implemented causal/diff/semantic/G-Eval analyzers that answer which prompt caused a failure and whether a change helped.
  - Designed a local-first trace store so proprietary prompts stay on-machine.
  - Shipped provider-agnostic tracing (OpenAI/Anthropic/Gemini/Groq/Ollama/custom) with 2-line integration.
- **Hardest problem:** evaluating "did this prompt change help" rigorously — solved with semantic diffing plus G-Eval rule checks instead of eyeballing outputs.
