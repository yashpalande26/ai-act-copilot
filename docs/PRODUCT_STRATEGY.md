# AI Act Copilot: Product Strategy (21 Sep 2026)

## Core finding
Grounded, cited Q&A over the Act is table stakes, not a moat: a direct competitor (Legalithm) ships the "cited + abstains + classify -> obligations" flow free through ~2028, the EU's own Compliance Checker does basic classification, and a general LLM with the PDF approximates the chat. "No-hallucination cited Q&A" is a feature, quickly commoditised.

## The defensible product
The artifact + workflow + monitoring, not the chat. Reuse existing pieces: the deterministic classifier (risk-tier), the grounded RAG (evidence/citation layer), and query_trace (the dated audit record).

## The wedge to build first
"Describe your AI system -> grounded risk-tier classification (prohibited / high-risk / transparency-only / minimal) -> role-aware obligations (provider vs deployer) -> exportable, dated, cited report." Build v1 deterministic end to end: a structured questionnaire -> the classifier -> the report assembled from VERBATIM provision text plus citations. The classification VERDICT is deterministic and needs no eval. Any LLM-generated obligation or summary TEXT is eval-gated per CLAUDE.md invariant 3, so v1 contains none: no LLM legal prose, nothing to eval, every line traceable to quoted Official Journal text. An LLM plain-language layer (and free-text plain-language input) is a separate enhancement, gated on both the eval suite and the API budget.

## Differentiation (honest)
Not "no hallucination." It is: (a) exportable artifact quality (Annex IV technical file, FRIA, readiness report); (b) regulatory-change monitoring (recurring revenue, hard for a raw LLM); (c) EU hosting / security posture; (d) a vertical focus (e.g. HR-tech / recruitment = unambiguous Annex III high-risk) plus the consultancy channel.

## Honesty as an edge
SME penalties are "lower of" (Art 99(6)): a EUR 2M startup breaching Art 5 is ~EUR 140k, not EUR 35M. Ship a correctly-calibrated penalty calculator; do not fear-monger. More credible than rivals and matches the project's honesty rule. The shipped calculator must compute from the quoted article text (the percentage and fixed-amount ceilings as written) and the user's own turnover input, never from a hardcoded number; the ~EUR 140k above is illustrative only and must not appear in the product.

## Timeline (as of Sept 2026; MONITOR for change)
Digital Omnibus (Reg (EU) 2026/1744, in force 27 Jul 2026) deferred high-risk obligations to 2 Dec 2027 (Annex III) / 2 Aug 2028 (Annex I). Still live now: Art 5 prohibited practices, Art 50 transparency, GPAI obligations, and the penalty framework. Any deadline the tool states must be dated and monitored (itself a feature).

## Monetization
Free classifier + honest penalty calculator as the funnel. Paid: per-report EUR 200-600, or EUR 1k-5k / product / year. Recurring hook: monitoring subscription ~EUR 100-400 / mo. Highest realistic ACV for a solo founder: white-label / per-seat to consultancies and boutiques.

## Go-to-market
Sell the artifact, not the chatbot. Lead with "a cited, dated report that satisfies your customer's security review / an Annex IV draft." Go through the consultancy channel first (one partner = many clients, they carry liability sign-off). Target a vertical with a live trigger (HR-tech, or chatbot/GPAI on Art 50).

## Validate before over-building
Ship the free classifier + penalty calculator. Threshold before investing in paid artifact generation: ~50 assessments run and 3+ users asking "can I export/share this?".

## Key risk
Legalithm free-through-2028: if it starts charging, room opens on price/quality; if it stays free, avoid head-on self-serve and go channel/vertical.

## Liability line
Never claim to certify compliance or replace counsel. Ground every statement in quoted Official Journal text, label commentary as commentary, abstain on borderline calls, and keep SaaS "no legal advice" terms with a liability cap.
