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