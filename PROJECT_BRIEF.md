# PROJECT BRIEF — AI Act Copilot
*Single source of truth. Lives in the repo root (canonical) and mirrored into the Claude Project knowledge section so every chat shares the same end goal. Last updated: 19 Sep 2026 (v3 — retrieval + generation + eval Wave 1 complete; deferred-items register added).*

---

## 0. How to use this document
North-star reference for the whole build. Any new chat in this project reads this first. States **what we're building, why, the architecture, the phased plan, the principles, and current status.** When decisions change, update this file — it is the canonical record.

**Two copies, kept in sync:** the repo-root copy is canonical (Claude Code reads it); the Claude Project knowledge copy is what the planning chat reads. When status materially changes, refresh both.

- **Repo:** `ai-act-copilot` (private GitHub, backend-first monorepo)
- **Builder:** Yash Palande — solo engineer, Dublin. Primary aim: **learn the full software + AI engineering lifecycle deeply** by building a real product. Secondary: a genuinely useful tool with a credible path to a business.
- **Ambition level:** senior-level, production-intended application. NOT a learning toy. Solve hard problems properly rather than scoping around them.
- **Working model:** planning/teaching chat gives steps + teaching → Yash runs them through Claude Code (in Cursor) → pastes results → verify → next step.

---

## 1. TL;DR / North star
A **grounded, evaluation-first compliance copilot** that tells someone whether their AI system falls under the EU AI Act, **why** (with verbatim citations to the legal text), and what their obligations are — architected so it **cannot confidently make things up** on a topic where being wrong is costly.

- **v1 corpus:** EU AI Act (cleanest deterministic classification; already researched and partially verified).
- **North star (v3):** multi-regulation **compliance-evidence copilot** for EU financial services (DORA, GDPR Art 22) — the builder's fintech domain.
- **The product is trust:** deterministic verdicts + cited explanations + measured groundedness. The evaluation harness proving it works is the centrepiece, not an afterthought.

---

## 2. The problem
Companies building or using AI in the EU face real, enforceable regulation buried in dense legal text. Most teams don't know where they stand, can't afford €30k+ enterprise GRC suites or lawyers, and get confident-but-wrong, uncited answers from general chatbots. **The information is public but not usable, and being wrong has consequences.**

## 3. What we're building
User describes their AI system and gets:
1. **A verdict** — e.g. "HIGH-RISK under Annex III" — from a **deterministic rules engine** (reproducible, not AI-generated).
2. **A grounded explanation** — a copilot answers "why?" and "what now?", quoting the exact article with a link. If the law doesn't cover it, it says so instead of guessing.
3. **(Later) documentation scaffolding + a tamper-evident audit log.**

**Example:**
> **User:** "We're a Dublin startup; our app uses AI to score loan applicants."
> **Tool:** "⚠️ HIGH-RISK. Trigger: Annex III, point 5(b) — creditworthiness evaluation of natural persons. Obligations apply from 2 Dec 2027: risk management, technical documentation, human oversight, record-keeping." *(each claim cites the article)*

## 4. Who it's for
EU startup founders, developers, and small-company compliance owners needing a fast, trustworthy, self-serve read on their obligations — the segment expensive enterprise GRC tools ignore.

## 5. Positioning & honesty stance
- **Informational, not legal advice.** Mandatory framing; human sign-off for anything acted on.
- **Only the Official Journal text is legally authentic** — consolidated EUR-Lex text is documentary value only. Every answer is pinned to a corpus version.
- **Differentiation vs "just ask ChatGPT":** deterministic + reproducible verdicts, verbatim citations to the *current* consolidated text, and a *measured* groundedness rate.

---

## 6. Architecture (locked)
Core pattern (proven in the builder's fintech work): **keep deterministic logic OUT of the LLM path; wrap it in an advisory, grounded AI layer.**

1. **Deterministic classification engine (code, not LLM).** Encodes Annex III / Art 5 / Art 50 rules → risk tier + triggering article + obligations + deadlines. Auditable, unit-tested, reproducible. *This is the verdict.* [BUILT — financial slice]
2. **Grounded RAG copilot (advisory).** Retrieval over the official AI Act text on Postgres + pgvector. Every answer carries enforced citations; ungrounded output is blocked. [BUILT — hybrid retrieval + grounded generation with abstention]
3. **Guardrails.** Prompt-injection detection, groundedness gate, abstention. [PARTIAL — abstention built; injection detection + groundedness gate deferred]
4. **Human-in-the-loop.** Low-confidence classifications escalate. [DEFERRED — v2]
5. **MCP.** Expose classifier + retrieval as MCP tools. [DEFERRED — v2+]
6. **Evaluation harness (the spine).** Golden Q/A set, groundedness/faithfulness, citation precision, retrieval recall@k, LLM-as-judge, CI regression gate, tracing + cost/latency. [Wave 1 BUILT — deterministic golden-set metrics; Wave 2 (LLM-as-judge) + CI gate + tracing deferred]

### 6.1 Locked technical decisions (from deep research, Sep 2026)
- **Source:** EUR-Lex consolidated **XHTML**, CELEX `02024R1689-20260727` — NOT the PDF. Authoritative markup beats PDF extraction.
- **Chunking:** structural-unit. Paragraph/point = embedded unit; article = parent returned for generation (small-to-big). Contextual prefixes generated once at ingest.
- **Retrieval:** hybrid — pgvector cosine + Postgres full-text (tsvector), fused with **Reciprocal Rank Fusion (k=60)**. Lexical is non-optional in principle (embeddings blur "Article 6(2)"). *NOTE: Wave 1 eval showed the lexical half is currently inert on real queries — see ADR-7 and §17.*
- **Reranker:** add ONLY if the eval harness proves lift. (LegalBench-RAG found general rerankers can *hurt* on legal text.)
- **Embeddings:** `text-embedding-3-large` at **1536 dims** (3072 risks exceeding pgvector's indexable limit). Reversible behind eval; legal-domain models (Voyage/Kanon) are a later A/B.
- **Index:** HNSW with `vector_cosine_ops` (must match the `<=>` query operator or it silently falls back to a sequential scan).
- **Corpus versioning:** bitemporal from day one — the Act has already been amended once.
- **Background processing:** NONE for v1. Ingestion is a CLI batch job. Add `arq` (not Celery) only when durable, retryable, concurrent work exists.
- **Deferred deliberately:** LangGraph/agentic retrieval, Celery/Redis, reranker, dedicated vector DB, fine-tuned embeddings.

### 6.2 EUR-Lex source structure — VERIFIED by spike (14 Sep 2026)
Inspected the real HTML (854 KB, CONVEX-generated). Findings that override the research assumptions:
- **Stable IDs exist ONLY at article/annex level:** `id="art_6"`, `id="art_6.tit_1"`, `id="anx_III"`. Safe parser anchors.
- **NO stable IDs below that.** Paragraph/point markers are bare `<span class="no-parag">1. </span>` and `<span>(b) </span>`. Other `id="id-<uuid>"` attributes are converter-generated and NOT stable — ignore them.
- **Implication:** citation depth ("Article 6(2), point (a)") must be **computed** by walking nested `grid-container grid-list` blocks. We own our citation scheme (e.g. `art_6.par_2.pt_a`), derived from position.
- **Amendment markers are inline:** `M1` (inserted by Reg 2026/1744) / `B` (base text resumes), woven into article bodies via `<p class="modref">`. Must be stripped from text but recorded as provenance.
- **Recitals are ABSENT** from the consolidated text (operative text only: title, articles, annexes). If recital citations are wanted later, the original `32024R1689` OJ document is a separate source. -> v2 corpus item.
- **Verified against source:** Annex III point 5(b) contains the fraud carve-out inline ("...with the exception of AI systems used for the purpose of detecting financial fraud"), confirming the deterministic engine's rules are substantively correct.
- **Document scale:** 119 articles (113 numbered + 6 inserted by the amendment: art_4a, art_60a, art_75a-art_75d), 14 annexes (anx_I - anx_XIV).

**Markup patterns for the parser:**

| Purpose | Pattern |
|---|---|
| Article wrapper | `<div class="eli-subdivision" id="art_N">` |
| Article number | `<p class="title-article-norm">Article N</p>` |
| Article title | `<div class="eli-title" id="art_N.tit_1"><p class="stitle-article-norm">` |
| Numbered paragraph | `<div class="norm"><span class="no-parag">1. </span>...` |
| Points (a)/(b) | `<div class="grid-container grid-list">` -> `grid-list-column-1` (marker) + `grid-list-column-2` (text) |
| Annex | `<div id="anx_III">`, `<p class="title-annex-1">` / `title-annex-2` |
| Amendment | `<p class="modref">` with `M1` / `B` |

**Source URL for ingestion:** `https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02024R1689-20260727` (requires a browser User-Agent header).

---

## 7. Phased roadmap

### v1 — Prove the engine
- Deterministic classifier (Annex III point 5 slice first, then expand) as pure, tested code. [DONE]
- `POST /classify` endpoint. [DONE]
- Postgres schema with corpus versioning + provisions hierarchy. [DONE — 9 tables + Alembic]
- Ingestion pipeline: fetch -> parse -> chunk with computed provenance -> embed -> store. [DONE — 1,255 provisions, 1,128 chunks, all embedded]
- Hybrid retrieval (pgvector + FTS + RRF). [DONE — Step 22]
- Grounded generation with enforced citations + abstention. [DONE — Step 23]
- Golden eval set + deterministic retrieval/generation metrics. [DONE — Step 24, Wave 1]
- Eval Wave 2 (LLM-as-judge faithfulness/relevance) + CI regression gate. [TODO]
- Minimal Next.js chat UI with clickable citations. [TODO]
- **Deployed live** + README with the real metrics table. [TODO]

### v2 — Harden & make it agentic
Adaptive/agentic RAG routing (LangGraph) + reranker; guardrails; HITL escalation queue; Annex IV doc scaffolding; tamper-evident audit log; red-team eval suite; recitals corpus; MCP tools.

### v3 — Broaden toward the north star
Second corpus (DORA / GDPR Art 22); Irish national layer; evidence-pack export; memory; full regression-gated release pipeline.

## 8. v1 scope — explicit
**In:** deterministic classifier, classify endpoint, ingestion pipeline, hybrid retrieval, RAG copilot with citations, eval harness + CI gate, tracing/cost logging, minimal UI, live deploy.
**Out (deferred):** multi-corpus, guardrails, HITL, doc-generation, audit log, memory, auth/multi-tenant, agentic multi-hop retrieval, reranker (unless eval proves lift).

## 9. Defensible metrics (MEASURED, never invented)
- Classification accuracy/precision/recall vs a hand-labelled gold set.
- Groundedness / citation faithfulness. *Benchmark: purpose-built legal AI tools measured at 17-33% hallucination (Stanford RegLab, Magesh et al.); a lower, measured rate is a real result.*
- Retrieval recall@k, MRR; reranker lift (if any).
- Latency p50/p95; cost per run; CI regression-gate pass rate.

**Target thresholds (legal premium over general-domain defaults):** faithfulness >=0.85, answer relevancy >=0.80, context recall >=0.80, citation faithfulness = exact support. Calibrate against a hand-graded set; generic thresholds pass answers a domain expert would fail.

**Wave 1 measured results (19 Sep 2026, golden set of 20 — 16 answerable + 4 off-topic):**
- Recall@5: **1.000** (vector-only AND hybrid — identical)
- MRR: **0.896** (identical vector vs hybrid — lexical shifted zero ranks)
- Citation hit rate: **1.000** (16/16 answerable)
- Abstention accuracy: **1.000** (20/20)
- Golden set human-spot-checked against EUR-Lex: 5/5 labels verified correct.
- *Caveat (kept honest): 16 answerable questions is a small set (one miss ≈ 6pts of recall); semantic questions were LLM-generated then retrieved against the same model family, a mild self-agreement bias. This is a clean Wave 1 baseline, not proof of quality at scale. Wave 2 (LLM-judge) + a larger set are where it gets stress-tested.*

## 10. Tech stack
- **Backend:** Python 3.11, FastAPI 0.136.3, uvicorn 0.52.4, Pydantic 2.13.5.
- **DB:** PostgreSQL 16 + pgvector 0.8.6. **LIVE DB is Supabase** (managed Postgres + pgvector), connected via the Session pooler URI in `backend/.env`. The local `docker-compose.yml` is a dead leftover (see §17 / ADR-005) — all migrations, data and indexes are on Supabase. Alembic for migrations.
- **AI:** LangChain for orchestration (LangGraph deferred to v2); OpenAI as provider (BYO key, near-zero cost). Generation uses `gpt-4o` at temperature 0.
- **Eval:** Wave 1 is dependency-free (deterministic metrics via stdlib). Planned: DeepEval (pytest-native CI gate) + RAGAS (LLM-judge metrics) + Langfuse or Arize Phoenix (tracing) — all free/self-hostable, added only when a measured need justifies them.
- **Quality/CI:** ruff 0.16.7, pytest 9.1.1, GitHub Actions.
- **Frontend (later):** Next.js / React / TS.
- **Deploy:** cheap target (Railway / Fly / Vercel) — decided at deploy step.

---

## 11. Non-negotiable principles
1. **No fabricated metrics, tools, results, or capabilities — ever.** Verify legal facts against EUR-Lex before encoding.
2. **Deterministic core stays out of the LLM path.** The LLM explains; it never decides the verdict.
3. **Eval-first.** Define "good" with a golden set before tuning; measure groundedness, don't assert it.
4. **Don't over-engineer** — but "smallest correct solution" means no needless abstraction, NOT avoiding necessary engineering.
5. **Verify before recommending.** User suggestions and assistant assumptions are inputs, not conclusions. Research current industry practice; disagree with evidence.
6. **Design holistically.** Consider the whole system before implementing a piece; do design phases (e.g. schema) explicitly.
7. **Teach as we build.** Every concept/tool/decision explained with tradeoff + interview angle.
8. **Yash commits all git himself.** No AI-authored commits, no "Co-Authored-By" lines.
9. **Not legal advice.** Trust is earned through citations + measurement + human oversight.

## 12. How we work
- **Two Claudes:** planning chat = planner/teacher + strategy + learning log; Claude Code (Cursor) = executor. Yash is the middleman reviewing every step.
- **The loop, every step:** planner gives (1) short design rationale, (2) copy-paste prompt for Claude Code (ending with the constant closer `Follow CLAUDE.md.`), (3) what to verify. Yash runs it, pastes results. Planner verifies, then gives the LEARNING_LOG entry + next step.
- **Commit discipline:** after every build step the planner hands Yash the full git command(s) to commit + push himself. Claude Code never runs git. Any repo action that touches git (e.g. `git rm`) is Yash's to run, not Claude Code's.
- **Plan mode** in Claude Code for structural work; skip for trivial edits.
- **Answer style:** crisp bullet points, no long theory, always state the next step.
- **Four files:**
  - `PROJECT_BRIEF.md` — this north-star spec (repo root = canonical; mirrored to Project knowledge).
  - `DECISIONS.md` — ADR log of every non-obvious decision (repo root, committed).
  - `CLAUDE.md` — rules FOR Claude Code (committed). Holds the standing rules the tail line `Follow CLAUDE.md.` points to, including the git rule.
  - `LEARNING_LOG.md` — private learning notes, one entry per concept-bearing step (gitignored; authored by the planning chat; needs manual backup). Entry format: what we did / concept / why it matters / interview angle.

## 13. Current status (19 Sep 2026)
**Phase 1 — Foundation: COMPLETE.**
- Private GitHub repo, backend-first monorepo, venv, pinned deps
- FastAPI app with `/health`
- ruff, pytest, GitHub Actions CI — green
- `CLAUDE.md`, `DECISIONS.md`, `LEARNING_LOG.md`

**Phase 2 — Features: RETRIEVAL + GENERATION + EVAL WAVE 1 COMPLETE.**
- Domain models (Pydantic): RiskTier, UseCase, SystemDescription, ClassificationResult [DONE]
- Deterministic classifier engine (Annex III point 5 financial slice), branch tests [DONE]
- `POST /classify` endpoint + integration tests [DONE]
- EUR-Lex source structure verified by spike (see 6.2) [DONE]
- Full 9-table SQLAlchemy schema + Alembic migration (corpus_version, provision, provision_reference, chunk, chat_session, message, citation, classification_run, app_user); bitemporal-ish versioning; append-only audit columns [DONE]
- DB migrated to and live on **Supabase** [DONE]
- Ingestion: fetch (content-hashed) → parse EUR-Lex HTML → **1,255 provisions** (119 articles + 8 annexes; 6 annexes deferred per ADR-004) [DONE]
- Chunking → **1,128 chunks** with contextual prefixes [DONE]
- Embeddings → all 1,128 embedded (1536-dim), resumable/idempotent [DONE]
- Indexes: HNSW (cosine) + GIN full-text via migration; verified used via EXPLAIN [DONE]
- **Step 22 — Hybrid retrieval:** `keyword_search()` (Postgres FTS) + `rrf_rank_and_fuse()` (RRF, vector 0.7 / lexical 0.3, k=60) [DONE]
- **Step 23 — Grounded generation:** `generate_grounded_answer()` — closed-context gpt-4o @ temp 0, citations persisted from retrieved chunks (never parsed from model prose), fixed abstention with two convergent paths [DONE]
- **Step 24 — Eval harness Wave 1:** source-grounded golden set (20 entries) + deterministic runner (Recall@5, MRR, citation hit rate, abstention accuracy) + pure-function metric tests [DONE]
- Full test suite: 58 passing.
- **NEXT: eval Wave 2 (LLM-as-judge faithfulness/relevance) OR the ADR-7 lexical fork — planner to sequence.**

## 14. Key decisions & rationale
- **AI Act as v1 corpus:** cleanest deterministic classification; deeply researched. DORA/GDPR deferred to v3. *(Flip-able — architecture is identical.)*
- **Single corpus in v1:** prove the engine before breadth.
- **Deterministic-first, then RAG:** build the trustworthy core before the advisory layer; needs no external services.
- **Fresh repo, not a ScoutAI fork:** learn each decision from the ground up; ScoutAI kept as a *reference* for the agent/streaming layer.
- **Eval-first:** the key senior-level differentiator for 2026 AI engineering.
- **RRF over score normalization:** fuse retrievers by rank, not raw score — cosine (~0-1) and `ts_rank_cd` (unbounded, corpus-dependent) are incomparable magnitudes; normalization goes stale as the corpus grows. (ADR / Step 22.)
- **Citations persisted from retrieval, not model prose:** the audit trail is built from what we fed the model, so it survives even if the answer text forgets to cite. (Step 23.)
- **Deterministic eval before LLM-judge:** Wave 1 is free, reproducible, defensible; RAGAS-style LLM-judge is added only once a measured gap justifies it. (Step 24.)
- **Not a legal-research copilot or eval platform:** those markets are capital-intensive and consolidated (Harvey ~$11B, Legora ~$5.5B; Braintrust/Langfuse/LangSmith well-funded). A vertical, self-serve, cited, measured compliance tool is where a solo builder is credible.

### Verified dates (EUR-Lex, Sep 2026)
The Digital Omnibus (**Regulation (EU) 2026/1744**) is enacted and in force since **27 July 2026**. It deferred:
- **Annex III high-risk obligations -> 2 December 2027**
- **Annex I product high-risk -> 2 August 2028**
- **Article 50 transparency was NOT deferred — applies since 2 August 2026**
- Prohibited practices + AI literacy: since 2 February 2025. GPAI: since 2 August 2025.
- Article 5 now prohibits **ten** practices (eight since Feb 2025, two added by the Omnibus).
- Harmonised standards (CEN-CENELEC JTC 21) are **not yet published** — no presumption of conformity exists yet.

## 15. Known risks
- **Cross-reference resolution** ("as referred to in Article 6(2)") — the hardest retrieval problem for this corpus; needs a reference graph. *Related: ADR-6 (exact article-reference lookup is a structured-metadata path, not a full-text/vector one).*
- **Judge nondeterminism** in CI — mitigate with pinned judge model, N-run aggregation, deterministic sub-gates.
- **Provenance drift on amendment** — bitemporal versioning is the insurance.
- **Over-trusting a green eval** — a passing faithfulness score can still ship a wrong-but-plausible legal answer. Keep a human-graded calibration set. *Wave 1's 1.000s are a small-sample baseline, not a quality guarantee (see §9 caveat).*

---

## 16. Decision log index (ADRs — full text in DECISIONS.md)
- **ADR-004** — 6 annexes (I, VII, VIII, X, XI, XIV) deferred: different section structure needs a new parser.
- **ADR-005** — `docker-compose.yml` fate: originally "keep for offline fallback," but Supabase is the sole live DB and the file has repeatedly caused local-vs-Supabase confusion. **Resolution pending Yash's call** (supersede ADR-005 and `git rm` the file, or keep it and stop treating it as dead).
- **ADR-6** — exact article-reference lookup deferred: detect citation pattern in query → direct `citation_id` lookup; revisit once eval quantifies how often it's needed.
- **ADR-7** — lexical retrieval inert as built: decided fork (see §17).

## 17. Deferred / To-Verify register
*Single place for everything we consciously postponed, so no chat loses it. The files remember; nothing else does. Review this section at the start of each new phase.*

**Deferred decisions (settled we'd wait — logged as ADRs):**
- **ADR-6** — exact article-reference lookup (query citation-pattern → direct `citation_id` lookup). Deferred until eval quantifies need.
- **ADR-7** — lexical retrieval adds nothing as currently built. Confirmed by Wave 1: even a golden set built specifically to favor lexical (4 questions on rare, verified verbatim phrases) produced zero rank contribution — root cause is `websearch_to_tsquery` AND-semantics on full-question phrasing (every stemmed word must co-occur in one chunk), not the corpus. **Open fork for a later step:** (a) fix query construction — extract key terms / OR-join before `websearch_to_tsquery`; or (b) drop the lexical half and ship honest vector-only. Decide with the eval numbers in hand.

**Deferred build work:**
- **Eval Wave 2** — RAGAS-style faithfulness / answer-relevance via LLM-as-judge (gpt-4o-mini). Add only once Wave 1 gaps justify it.
- **CI regression gate** — wire eval metrics into GitHub Actions to block regressions (DeepEval, pytest-native).
- **Observability / tracing** — Langfuse or Arize Phoenix. Planned for the eval/observability phase; nothing built yet. *This is where the eval numbers get a dashboard instead of terminal output.*
- **Audit logging** — `classification_run` table population. Planned, not built.
- **Integration-test DB cleanup** — the generation + eval integration tests write real rows to Supabase (`message`, `citation`, throwaway `app_user`/`chat_session`, emails prefixed `integration-test-<uuid>@`) with no teardown. Add a pytest fixture that rolls back / cleans up. Fold into the next task that touches those tests.
- **6 unparsed annexes** (I, VII, VIII, X, XI, XIV) — section-structure parser + parentage verification (ADR-004). Annex I matters for the product-safety high-risk route, outside the v1 financial flagship.
- **Poisoned-index guard** — verify no important free-standing legal sentences are silently un-retrievable (not captured as provisions).
- **`embed.py --help`** — runs instead of showing usage; fix when next touched (minor).

**Security (before the repo ever goes public):**
- **Rotate the Supabase DB password** — it appeared in terminal output during setup.

## 18. Glossary
- **RAG** — Retrieval-Augmented Generation: fetch relevant source text, then answer *from* it.
- **Agentic RAG** — RAG where the model can loop: retrieve, reason, decide to retrieve again.
- **Deterministic classifier** — plain code, same output for same input, auditable, no LLM.
- **Groundedness / faithfulness** — whether claims are actually supported by retrieved source text.
- **Golden set** — hand-authored question->correct-answer dataset used to measure quality.
- **LLM-as-judge** — using an LLM to score outputs against a rubric during evaluation.
- **RRF** — Reciprocal Rank Fusion: merges ranked lists from different retrievers by rank, not score.
- **Recall@k / MRR** — retrieval metrics: did the right chunk appear in top-k / how high did the first correct one rank.
- **Bitemporal** — tracking both when a fact was true in the world and when it was recorded.
- **Guardrails** — input/output filters (injection detection, groundedness enforcement, PII).
- **HITL** — human-in-the-loop review of low-confidence or high-stakes outputs.
- **MCP** — Model Context Protocol: standard for exposing tools/data to AI agents.
- **CI regression gate** — automated check blocking a release if quality metrics drop.
