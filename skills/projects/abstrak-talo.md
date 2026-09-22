# Abstrak Labs / Talo — AI Freelancer ($10/hr) Site + Lead Engine

Repo: `techwarq/abstraklabs` · Site: `talo.abstraklabs.com` · Next.js + TypeScript · Sep 2026 (actively shipped)

## What I built
The marketing, lead-gen, and proof site for **Talo — hire an AI freelancer from $10/hour** for research, data, lead generation, browser work, and document processing. Not another AI tool: you describe the job in plain English, the agent does it, you pay for time used. Includes a `/hire` chat UI that captures name+email and submits tasks straight to a leads API, service pages per offering, proof/work case-study pages, and full SEO/OG metadata.

## Why I built it
Teams drown in boring, repetitive, research-heavy work nobody wants to do. Positioning insight: *you buy the result, not the software* — no prompting, no workflows, no subscription to learn.

## How I built it
- **Stack:** Next.js (app router) + React + Tailwind + framer-motion, Vercel Analytics.
- **Conversion flow:** `/hire` redesigned as a slick chat UI; captures name+email upfront and submits tasks directly to the leads API (shipped Sep 2026).
- **Service pages:** ai-research, ai-data-entry, ai-data-cleaning, ai-lead-generation, ai-document-processing, ai-invoice-processing, ai-web-research, ai-ecommerce-operations, ai-crm-cleanup, ai-freelancer — each with its own route, metadata, and CTA.
- **Proof pages:** real engagements as RESEARCH→FILTER→VERIFY→ENRICH pipelines with time/cost/deliverable numbers.
- **Distribution polish:** shared `og-image.png` wired into per-page Open Graph/Twitter metadata (fixed blank Twitter cards by pointing `siteUrl` at the `www` subdomain), sitemap + robots, accent-color system refresh.

## Proof
- 500 US SaaS companies + founders/funding/LinkedIn delivered in **6h 42m for $67**; 1,200 ICP LinkedIn profiles in **4h 12m for $42**. Waitlist live with 50%-off launch offer.

## For job forms (copy-paste)
- **One-liner:** Built the Next.js marketing + lead-gen site for an AI-freelancer service, including a chat-based hire flow wired to a leads API and case-study proof pages.
- **Bullets:**
  - Shipped 10+ SEO'd service pages and a `/hire` chat UI that captures and submits qualified tasks.
  - Fixed social-preview reliability (OG/Twitter metadata, subdomain canonicalization) and site-wide design system updates.
  - Published real delivery metrics as proof content (500-company research sprint: 6h42m, $67).
- **Hardest problem:** making link previews deterministic across crawlers — traced blank Twitter cards to a bare-domain vs `www` routing mismatch and standardized metadata site-wide.
