# CLAUDE.md — AI Act Copilot

## What this project is
A copilot that classifies whether an AI system is high-risk under the EU AI Act and answers "why," grounded in official sources with citations. Deterministic rules engine decides the verdict; the LLM is advisory only and never decides risk tier.

## Who I am
Yash — solo engineer, ~3 yrs experience. I am LEARNING the full engineering lifecycle by building this. Teach me; don't just produce code.

## Non-negotiable rules
- NEVER fabricate metrics, results, or capabilities. Real, defensible numbers only.
- Do NOT over-engineer. Smallest correct solution. No abstractions until needed.
- Do NOT charge ahead on assumptions. If unclear, ask me first.
- I commit ALL git myself. NEVER run git commit. NEVER add "Co-Authored-By: Claude" or similar.
- Explain every new concept, tool, and decision in plain language, with the tradeoff — I am here to learn.
- Mid-level framing, not senior/architect.

## How we work
- Use plan mode: propose the plan, wait for my approval before editing files.
- One step at a time. Do not scaffold the whole project at once.
- After each step, briefly state what changed and why.

## Stack (backend-first)
Python 3.12+, FastAPI, PostgreSQL + pgvector, LangGraph/LangChain, BYO API key. Monorepo: backend/ first, frontend/ later.

## Research and design discipline
- Verify against current industry practice before recommending. User suggestions and my assumptions are inputs, not conclusions.
- Research what senior engineers are actually doing in 2026 for the problem at hand; cite it; disagree with evidence when warranted.
- Design holistically: consider the whole system (data model, users, retrieval, citations, audit) before implementing a piece.
- Do the design phase explicitly (e.g. schema design before tables), don't discover it mid-build.

## Engineering invariants — check these, don't just follow the steps
1. Symmetry of compared/fused components: any two things compared or combined (e.g. two
   retrievers fused by RRF) MUST operate on the same representation/inputs. Before comparing
   or fusing, verify they see the same data; flag any asymmetry explicitly.
2. Eval validity before eval results: for any eval, state the failure class it CANNOT see by
   construction. An eval whose questions are generated from the same field the system
   indexes/returns is blind to failures in the un-indexed parts — treat its numbers as
   provisional until validated on out-of-sample, real inputs.
3. Never ship on curated-eval green alone: validate any retrieval/quality change on
   out-of-sample real queries before recommending it ships. Green on a curated (especially
   adversarially-built) set overstates.
4. Adversarial eval tiers: report per-category, never a pooled headline; name the bias.
5. Review depth by reversibility: production/schema/irreversible changes get
   plan -> verify -> execute; exploration/research/measurement runs autonomously and reports once.