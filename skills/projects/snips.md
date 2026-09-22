# Snips AI — Research Papers Explained Simply

Site: `usesnips.com` · "Beat the Brainrot" · Web app, free to try, no card/account needed

## What I built
Snips AI fixes the format of research papers. Drop a PDF or paste an arXiv link and every concept becomes a **scrollable card feed**: each card starts with the simplest possible explanation (ELI5, no assumed knowledge), and one tap on "Dive deeper" reveals full technical depth — precise language, equations with context, analogies, and connections to related concepts. Example: *Attention Is All You Need* (47 pages) becomes 18 cards. I use it myself daily while building.

## Why I built it
Research papers aren't written to be understood — they're written to be published. You read the first paragraph three times, hit a term with no context, close the tab. As I put it: *"there's decades of research hiding under cryptic paper titles, begging for practical application."* I wanted to understand papers in 20–30 minutes on the go, without chatting back-and-forth with an AI.

## How I built it
- **Ingestion:** PDF/arXiv-link intake that reads the paper page by page, identifies every concept, and builds the card feed.
- **Agentic pipeline:** describe the actual problem you're solving and it agentically finds relevant papers, explains them simply, extracts useful architectures/ideas, and turns them into practical implementation plans.
- **Two-level explanation engine:** level 1 = simplest possible framing ("attention is a soft lookup table — like calling a friend's name in a crowd"); level 2 = full math (`Attention(Q,K,V) = softmax(QKᵀ/√d_k)·V`), scaled-dot reasoning, and cross-concept links.
- **Product loop:** beta users' feedback ("decades of research…") directly reshaped the product toward problem-first explanations.
- Web app, no install; 1 paper free.

## Proof
- Live at usesnips.com with pricing + sign-in; beta users active; best-performing launch post: *"feels like having a research engineer sitting beside you while you work."*

## For job forms (copy-paste)
- **One-liner:** Built an AI web app that turns dense research papers into simple scrollable concept cards with two-level (ELI5 → full technical) explanations.
- **Bullets:**
  - Built an agentic pipeline that finds relevant papers from a problem description, explains them simply, and extracts architectures into implementation plans.
  - Designed a two-level explanation engine pairing plain-English analogies with equations-in-context.
  - Shipped a live freemium web app (free trial, no card) and iterated it from real beta-user feedback.
- **Hardest problem:** calibrating "simple but not wrong" — explanations must survive the dive-deeper transition from analogy to exact math without contradicting themselves.
