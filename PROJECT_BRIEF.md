# PROJECT BRIEF — AI Act Copilot
*Single source of truth. Lives in the repo root (canonical) and mirrored into the Claude Project knowledge section so every chat shares the same end goal. Last updated: 20 Sep 2026 (v4 — hybrid retrieval SHIPPED to production (vector + BM25 over index_text, RRF @ lexical 0.6); trace logging and eval infra complete; two eval sets; next is the chat UI).*

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
2. **Grounded RAG copilot (advisory).** Retrieval over the official AI Act text on Postgres + pgvector. Every answer carries enforced citations; ungrounded output is blocked. [COMPLETE — hybrid retrieval (vector + BM25, RRF @ lexical 0.6) shipped to the production answer path, with safe degrade to vector-only and per-turn trace logging]
3. **Guardrails.** Prompt-injection detection, groundedness gate, abstention. [PARTIAL — abstention built; injection detection + groundedness gate deferred]
4. **Human-in-the-loop.** Low-confidence classifications escalate. [DEFERRED — v2]
5. **MCP.** Expose classifier + retrieval as MCP tools. [DEFERRED — v2+]
6. **Evaluation harness (the spine).** Golden Q/A set, groundedness/faithfulness, citation precision, retrieval recall@k, LLM-as-judge, CI regression gate, tracing + cost/latency. [COMPLETE — Wave 1 deterministic metrics + Wave 2 LLM-as-judge; per-category Recall@5 / MRR / nDCG@10; three eval sets; `query_trace` / `retrieval_trace` logging per turn. CI regression gate still deferred]

### 6.1 Locked technical decisions (from deep research, Sep 2026)
- **Source:** EUR-Lex consolidated **XHTML**, CELEX `02024R1689-20260727` — NOT the PDF. Authoritative markup beats PDF extraction.
- **Chunking:** structural-unit. Paragraph/point = embedded unit; article = parent returned for generation (small-to-big). Contextual prefixes generated once at ingest.
- **Retrieval (SHIPPED):** hybrid — pgvector cosine + **BM25 (`bm25s`, in-process, IDF-weighted)**, fused with **Reciprocal Rank Fusion (k=60)** at **vector 0.4 / lexical 0.6**, candidate breadth 10. The original Postgres full-text leg was measured inert, its OR-join fix regressed precision, and both were replaced by BM25 (ADR-7).
  - **The sparse leg indexes `index_text` — the SAME text the dense leg embeds** (contextual prefix: `EU AI Act — Article 16 (Obligations of providers of high-risk AI systems), point (a):` + body). This follows contextual retrieval (Anthropic): prepend context *before embedding AND before creating the BM25 index*.
  - **Why it matters — a real bug, not theory.** BM25 previously indexed `chunk_text` (body only) while vectors embedded `index_text`. That asymmetry made the sparse leg blind to article headings: for *"What obligations apply to providers of high-risk AI systems?"*, gold `art_16.pt_a` has a body reading only "ensure that their high-risk AI systems are compliant with the requirements set out in Section 2;" — the query's discriminating terms **"obligations"** and **"providers"** exist only in the heading. BM25 ranked it nowhere in its top 50, RRF dropped it, and the copilot **abstained on a question vector-only answered**. Over `index_text` it ranks 2nd and is cited first.
  - **Degrade path:** stale index (corpus-version mismatch) → raises → caught → logged loudly → vector-only; missing index → `[]` → vector-only. Production is never down and never serves citations resolved against the wrong mapping. `query_trace.retrieval_config` records which actually ran (`hybrid_bm25` / `vector_only_degraded`).
- **Reranker:** add ONLY if the eval harness proves lift. (LegalBench-RAG found general rerankers can *hurt* on legal text.) Now gated on the heading-aware eval set — v2 experiment.
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
- Ingestion pipeline: fetch -> parse -> chunk with computed provenance -> embed -> store. [DONE — 1,459 provisions, 1,336 chunks, all embedded; 119/119 articles retrievable since ADR-28; Annex I since ADR-29; 180 recitals since ADR-32]
- Hybrid retrieval (pgvector + BM25 + RRF @ lexical 0.6, shipped to production). [DONE]
- Grounded generation with enforced citations + abstention. [DONE]
- Query + retrieval trace logging (`query_trace` / `retrieval_trace`). [DONE]
- Eval infra: Wave 1 deterministic metrics + Wave 2 LLM-as-judge + per-category Recall@5 / MRR / nDCG@10, across `golden_set.yaml`, `golden_set_hard.yaml`, `golden_set_realistic.yaml`. [DONE]
- **NEXT → Minimal Next.js chat UI with clickable citations.** [TODO]
- **Then → Deployed live.** [TODO]
- **Then → README with the real metrics table.** [TODO]
- CI regression gate wiring eval metrics into GitHub Actions. [TODO — deferred, not blocking the UI]

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

**Shipped retrieval config measured (20 Sep 2026) — Recall@5 / MRR / nDCG@10, breadth 10, k=60:**

| config | realistic (56) | hard (35) | easy (16) |
|---|---|---|---|
| vector_only | 0.982 / 0.875 / 0.902 | 0.914 / 0.563 / 0.660 | 1.000 / **0.896** / **0.923** |
| **hybrid@0.6, BM25 over `index_text`** | **1.000 / 0.939 / 0.955** | **1.000 / 0.902 / 0.927** | 1.000 / 0.885 / 0.914 |

- Hybrid **beats vector-only on the realistic and hard sets**, and is **~parity on easy** — it gives up 0.011 MRR there (0.896 → 0.885), roughly one question slipping one rank out of 16, inside this corpus's noise floor.
- The diagnostic that justified the change: on the `heading_dependent` tier, the sparse leg over `chunk_text` scored **0.867 / 0.783** vs **1.000 / 0.852** over `index_text` — the only config that failed to retrieve heading-dependent golds. Sibling discrimination was *not* traded away (`near_duplicate` identical at 1.000/0.875 both sparse legs, 1.000/1.000 both fused).
- Weight 0.6 beat 0.5 on all three sets independently, which is better evidence than a peak on any single set.
- *Caveat: all three sets are LLM-generated; none is human-authored. 5 of 7 flagged realistic-set labels are still unverified against EUR-Lex (§17). Differences under ~0.02 MRR at these sample sizes are probably noise.*

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
- **Planner review-check — verify cross-cutting invariants, not just each choice.** Before approving a plan, check the properties that span components, because a plan can be locally correct at every step and still wrong as a whole. Specifically: (1) **symmetry** — do any two things being compared or *fused* operate on the same representation? (2) **eval blind spots** — what failure class can this eval not see *by construction*? (3) **reversibility** — how hard is this to undo? The BM25 heading bug passed every step-level review and was caught by none of them: each decision was individually defensible, but nothing checked that the fused legs read the same field, and the eval was structurally incapable of showing the gap.
- **Review depth by reversibility.** Production path, schema/migrations, and anything irreversible get the tight loop: plan → approve → execute → verify by *causing* the failure, not mocking it. Exploration, research, and measurement run autonomously end-to-end and report once. Match the ceremony to the blast radius; don't spend plan-mode rigour on a throwaway probe, and don't skip it on the answer path.
- **Retrospective-to-rules habit.** When a bug escapes review, don't just fix it — ask what *class* of check would have caught it, and write that check into `CLAUDE.md` as a standing rule. That's how the Engineering-invariants block came to exist. Rules earned from real failures beat rules copied from blog posts.
- **See `CLAUDE.md` → "Engineering invariants — check these, don't just follow the steps"** for the standing, executable version of the above (symmetry of fused components; eval validity before eval results; never ship on curated-eval green alone; per-category reporting for adversarial tiers; review depth by reversibility).
- **Answer style:** crisp bullet points, no long theory, always state the next step.
- **Four files:**
  - `PROJECT_BRIEF.md` — this north-star spec (repo root = canonical; mirrored to Project knowledge).
  - `DECISIONS.md` — ADR log of every non-obvious decision (repo root, committed).
  - `CLAUDE.md` — rules FOR Claude Code (committed). Holds the standing rules the tail line `Follow CLAUDE.md.` points to, including the git rule.
  - `LEARNING_LOG.md` — private learning notes, one entry per concept-bearing step (gitignored; authored by the planning chat; needs manual backup). Entry format: what we did / concept / why it matters / interview angle.

## 13. Current status (20 Sep 2026)
**Phase 1 — Foundation: COMPLETE.**
- Private GitHub repo, backend-first monorepo, venv, pinned deps
- FastAPI app with `/health`
- ruff, pytest, GitHub Actions CI — green
- `CLAUDE.md`, `DECISIONS.md`, `LEARNING_LOG.md`

**Phase 2 — Features: RETRIEVAL, GENERATION, TRACE LOGGING and EVAL INFRA all COMPLETE.**
- Domain models (Pydantic): RiskTier, UseCase, SystemDescription, ClassificationResult [DONE]
- Deterministic classifier engine (Annex III point 5 financial slice), branch tests [DONE]
- `POST /classify` endpoint + integration tests [DONE]
- EUR-Lex source structure verified by spike (see 6.2) [DONE]
- Full 9-table SQLAlchemy schema + Alembic migration (corpus_version, provision, provision_reference, chunk, chat_session, message, citation, classification_run, app_user); bitemporal-ish versioning; append-only audit columns [DONE]
- DB migrated to and live on **Supabase** [DONE]
- Ingestion: fetch (content-hashed) → parse EUR-Lex HTML → **1,459 provisions** (119 articles + 9 annexes incl. Annex I with its two sections + 180 recitals from the original OJ act, ADR-32; 5 annexes still deferred per ADR-004 Step B) [DONE]
- Chunking → **1,336 chunks** with contextual prefixes (1,128 leaf paragraphs, points and annex points, 8 single-paragraph article bodies per ADR-28, 20 Annex I items per ADR-29, 180 recitals per ADR-32, one chunk each) [DONE]
- Embeddings → all 1,336 embedded (1536-dim), resumable/idempotent [DONE]
- Indexes: HNSW (cosine) + GIN full-text via migration; verified used via EXPLAIN [DONE]
- **Grounded generation:** `generate_grounded_answer()` — closed-context gpt-4o @ temp 0, citations persisted from retrieved chunks (never parsed from model prose), fixed abstention with two convergent paths [DONE]
- **Trace logging:** `query_trace` + `retrieval_trace` written per turn — latency, tokens, per-candidate RRF/vector/lexical ranks, `used_in_context`, and `retrieval_config`. Best-effort by design: an independent transaction that can never roll back or block the user's answer [DONE]
- **Eval infra [COMPLETE]:**
  - Wave 1 deterministic metrics (Recall@5, MRR, citation hit rate, abstention accuracy) + **nDCG@10**, reported **per category** for every retrieval config
  - Wave 2 LLM-as-judge (faithfulness + answer-relevance, blind, strict-JSON with defensive parsing)
  - `run_eval --hard` / `--retrieval-only` flags
  - **Two curated sets beyond the original:** `golden_set_hard.yaml` (41 entries, adversarially selected against vector-only — report per-category, never pooled) and `golden_set_realistic.yaml` (62 entries, **heading-aware**, no adversarial screening, with a `heading_dependent` tier verified to carry heading-only terms)
- **Hybrid retrieval SHIPPED to production:** vector + BM25 (`bm25s` over `index_text`) fused via RRF @ vector 0.4 / lexical 0.6, breadth 10, k=60, with safe degrade to vector-only [DONE]
- Full test suite: **83 passing**; ruff clean.
- **NEXT: minimal Next.js chat UI with clickable citations**, then live deploy, then the README metrics table.

## 14. Key decisions & rationale
- **AI Act as v1 corpus:** cleanest deterministic classification; deeply researched. DORA/GDPR deferred to v3. *(Flip-able — architecture is identical.)*
- **Single corpus in v1:** prove the engine before breadth.
- **Deterministic-first, then RAG:** build the trustworthy core before the advisory layer; needs no external services.
- **Fresh repo, not a ScoutAI fork:** learn each decision from the ground up; ScoutAI kept as a *reference* for the agent/streaming layer.
- **Eval-first:** the key senior-level differentiator for 2026 AI engineering.
- **RRF over score normalization:** fuse retrievers by rank, not raw score. Cosine similarity (~0-1, bounded) and a BM25 score (unbounded, corpus- and length-dependent) are incomparable magnitudes, and any normalization mapping between them goes stale as the corpus grows. Fusing by rank sidesteps the problem entirely — which is why the rationale survived swapping the lexical leg twice (Postgres `ts_rank_cd` → BM25) without touching the fusion code.
- **Citations persisted from retrieval, not model prose:** the audit trail is built from what we fed the model, so it survives even if the answer text forgets to cite. (Step 23.)
- **Deterministic eval before LLM-judge:** Wave 1 came first because it is free, reproducible and defensible. The LLM-judge layer (Wave 2 — faithfulness + answer-relevance, blind, strict-JSON) was added afterwards, once Wave 1's ceiling-level scores showed deterministic metrics alone couldn't tell whether an answer's *content* held up. Built as a thin custom judge rather than pulling in RAGAS — no new dependency for two prompts and a parser.
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
- **ADR-7** — **RESOLVED (20 Sep 2026): hybrid retrieval SHIPPED.** Native FTS was measured inert; its OR-join fix lifted hard-case ranking but regressed precision and was reverted; BM25 (`bm25s`, IDF-weighted) replaced it and now ships at RRF lexical 0.6 over `index_text`. Root cause of the late-breaking bug: BM25 indexed `chunk_text` while vectors embedded `index_text` — an asymmetry that made the sparse leg heading-blind. Breadth and a per-query router were both tested and rejected with numbers.
- **ADR-8** — **ACCEPTED (21 Sep 2026): retrieval breadth 25 / context slice 15.** List-type questions were truncated by retrieval, not generation (`used_recall` equalled `ctx_recall` at every setting). Enumeration mean recall 0.433 → 0.817; hard-set MRR 0.902 → 0.874, judged cosmetic because an answer-level judge held faithfulness (4.85 → 4.95) and relevance flat. Weights, `min_similarity` and RRF `k` unchanged. Per-call cost roughly triples, so `config.py` quota recalibration is owed before deploy.
- **ADR-9** — Jev (TypeSafe System One) as an **advisory** reranker / actor classifier, deferred behind a cheaper fix: try a deterministic actor tag from `citation_id` first, and only benchmark Jev against cross-encoder and open-weights alternatives if contamination (~6) survives it. If ever adopted it flags or down-weights only, never hard-decides, and stays out of the deterministic APPROVE/REFER/DECLINE path.
- **ADR-10** — **ACCEPTED (21 Sep 2026): deterministic actor prior.** A derived actor map in `app/retrieval/actor.py` (provider / deployer / importer / distributor / authorised_representative / None, one comment per row from corpus text) plus a conservative regex that fires only when a query names exactly one actor; mismatched candidates are soft-down-weighted (factor 0.25, chosen from a sweep) before the context slice, nothing removed. Enumeration contamination 6 → 0, ctx_recall 0.817 → 0.867; guard sets unchanged, no gold ever down-weighted. Advisory, grep-verified out of the classifier engine. This is the "cheaper fix first" that ADR-9 gated Jev behind, and it cleared the measured contamination on its own.
- **ADR-11** — **ACCEPTED (21 Sep 2026): environment-tagged `query_trace`, per-environment quota.** `app_env()` reads `APP_ENV` (default `dev`, invalid value raises); every trace row carries an `environment` column stamped at the single write site; `calls_today()` filters to the current environment, so local dev and pytest can never consume production's `DAILY_LIMIT_GLOBAL`. pytest forces `test` via `conftest.py`; `/health` exposes the environment; startup warns if Railway is detected without `APP_ENV=production`. Migration applied (backfill `dev 3 / test 9`), 115 passed / 5 skipped with zero paid calls. **Deploy rule: migrate before deploying code.**
- **ADR-12** — **ACCEPTED (21 Sep 2026): the assessment wedge, deterministic end to end.** Questionnaire (every question shows the provision it rests on) → pure rules engine → obligations quoted **verbatim** by citation id → Article 99 ceilings parsed from the live text and computed from the user's turnover. No LLM anywhere in the path (grep-tested), so no eval gate applies: there is no generated prose to judge. Article 5 matches are red flags, the 6(3) derogation is quoted never applied, Annex I is honestly incomplete. Now the product's front door; `classify()` untouched.
- **ADR-13** — **ACCEPTED (21 Sep 2026): saved assessments.** New `assessment` table (migration `6aa3cd421b84`). `POST /assessments` takes **answers only**; the server re-derives the result, so a client cannot save what it did not earn. Owner-scoped reads, 404 no-leak. `engine_version = assess-<ENGINE_MAJOR>.<rules_hash>`, a canonical SHA-256 of the rule data (logic changes still need a hand bump of `ENGINE_MAJOR`; first bump 1 -> 2 on 21 Sep 2026 for the turnover-0 ceiling fix). **Known limitation, not built:** reopening re-renders provision text live from the current corpus; not an immutable snapshot.
- **ADR-14** — **ACCEPTED (21 Sep 2026): export as a self-contained HTML record.** Option C over server-side PDF (native libraries on Railway) and a print stylesheet (browser-produced, drifts with the UI): the backend renders one standalone document from the same payload, stdlib only, inline CSS with the design tokens as literals, no scripts or external assets, print stylesheet, dated, cited, not-legal-advice. Owner-scoped; open in tab or download. Same live-re-render limitation as ADR-13.
- **ADR-15** — **ACCEPTED (22 Sep 2026): free-text extraction, eval-gated.** Prose -> per-field {value, quote} -> Answers; quotes must be verbatim (case and edge punctuation tolerant); the five legal characterisations are never pre-filled; unknowns block the engine until confirmed. Run 4: false inference 1%, legal-five 0/62, fabricated quotes passed 0/123, verdict after confirmation 93%. Same daily quota as chat; description stored admin-only; Gemini paid tier only if ever added. Pre-fill gap: Art 5(1)(f) and (h) never flagged.
- **ADR-16** — **ACCEPTED (22 Sep 2026): dense anchor in fusion.** Root cause: with RRF 0.4/0.6 a vector-only rank-1 chunk (0.0066) loses to any BM25 top-25 chunk (>= 0.0071), so definitions never entered the candidates. Anchor at floor 0.45, position 6. Broad set gold-in-context 9/14 -> 14/14; golden recall identical; off-topic 11/11 refused.
- **ADR-17** — **ACCEPTED (22 Sep 2026): answer from the governing provision.** One prompt paragraph; flagship 3/6 -> 6/6, definitions 6/6, ungrounded control 0/6, off-topic 22/22 refused, faithfulness 4.812 -> 4.938, hit 16/16, abstention 20/20. Quoted abstention now counts as a refusal.
- **ADR-18** — **ACCEPTED (22 Sep 2026): delete a chat.** Owner-scoped DELETE /sessions/{id}; query_trace gets its own user_id and a nullable chat_session_id (migration `d4f5a6b7c8e9`), traces are detached not deleted, the quota counts by user_id: deleting a chat cannot reset it or hide it from the admin viewer.
- **ADR-19** — **ACCEPTED / DEFERRED (22 Sep 2026): scope short-circuit shipped; follow-up rewrite built, flag off.** Greetings get a free scope notice before any paid call. The rewrite passed every hard gate (no regression, 0 hallucinated entities) but +12 points pooled against +30 required; `FOLLOWUP_REWRITE=1` enables it after a passing run. Migration `c9e1f2a3b4d5` (trace columns) applied.
- **ADR-20** — **ACCEPTED (22 Sep 2026): agentic RAG as a flag-gated LangGraph pipeline.** Five nodes (rewrite with dual retrieval, grader, verifier, decomposition) each measured against the plain path with a non-compensatory gate and on by default inside `AGENTIC_RAG`, which stays off in production. Stage 0 to full: pooled recall 0.964 to 1.000, citation accuracy 0.893 to 1.000, abstention F1 0.883 to 1.000, single-hop unchanged; p50 latency 2.3 s to 7.4 s, cost per turn +19%. Label-aware faithfulness judge; open items: verifier paraphrase over-abstention on gpt-4o, no prompt tuning yet.
- **ADR-21** — **ACCEPTED / DEFERRED (22 Sep 2026): plain-language system questions.** Chat may explain what the Act says about a TYPE of system, cited; it never certifies the user's specific system, which is the assessment's verdict. Query understanding (gpt-4o-mini, search terms only, fused with the question) plus explain-and-route generation and a deterministic verdict-leak gate. Gold corrected the same day: the Act does not name property or collateral valuation, so that question must route asserting no provision, which it does. Re-gate: plain_language recall 0.500 to 0.833, citation accuracy 0.333 to 0.667, F1_ans 0.500 to 0.800, 0 verdict leaks on 47 items, every other bucket identical; `QUERY_UNDERSTANDING` on by default inside `AGENTIC_RAG`.
- **ADR-22** — **ACCEPTED / DEFERRED (22 Sep 2026): intent gate on, clarifying follow-up off.** gpt-4o-mini sorts messages into social (deterministic template, name persisted on the conversation), offtopic (grounded refusal, no retrieval) and on_topic; 21/21 routed, 0 leaks, on-topic set identical. The clarifying question never fired because the grader proceeds on vague AI descriptions and the generator abstains instead; `CLARIFY_FOLLOWUP` stays off pending a trigger decision.
- **ADR-23** — **(22 Sep 2026): conversational chat lane beside the cited rag lane; daily caps env-switchable.** gpt-4o-mini with the conversation history for greetings, common knowledge and idea discussion, an injection guard before it, the verdict-leak and legal-statement detectors after it, and a handoff of formed Act questions to rag. Gated: 0 legal statements, 0 leaks on 64 messages, 4/4 injections blocked with 0 false blocks on 41 on-topic items, general chat 7/7 natural; `CHAT_LANE` on inside `AGENTIC_RAG`. Limit: a message naming an AI system goes to rag, so idea discussion in chat happens only without one.
- **ADR-24** — **ACCEPTED / flag DEFERRED (23 Sep 2026): clarifying follow-up fires on the generator's explain-mode abstention; the reply is one more pass through the normal path.** Trigger moved off the grader; the reply turn skips the gate, lane and rewrite, keeps the guard, and runs understand to verify once; whatever it decides stands. Explain instruction revised so function-less descriptions abstain instead of listing provisions (probe 3/3 on five items, already-clear still 3/3 answered). Clarify set: 12 of 13 gates, 0 leaks, 0 stretched provisions, underspecified asked 4/4 and grounded 3/4 on the second pass; the miss was the verifier withholding a correct 5(d) answer twice. `CLARIFY_FOLLOWUP` stays off until Yash decides on that gate.
- **ADR-25** — **ACCEPTED in part (23 Sep 2026): verifier is gpt-4o with passage headings; prompt loosening rejected; clarify flag still off.** 46-probe set (12 valid paraphrases incl. the real withheld answers, 10 false-accept traps), 3 draws each, 8 configurations: gpt-4o-mini let a wrong-label claim and an exclusion contradiction through 3/3 under every prompt; every loosening added false accepts; gpt-4o with headings is 0 false accepts on every draw with two arguable withholds (66(h) modality, 75(2) scope). On-topic: 0 leaks, faithfulness 0.850 to 0.872, citation accuracy 0.868 held. Clarify set 11 of 13 (understand-step coin flip on the vaguest item), triage 3 of 4 draws, so no flip.
- **ADR-26** — **ACCEPTED (23 Sep 2026): `CLARIFY_FOLLOWUP` on inside `AGENTIC_RAG` under a split gate.** Probe golds for Article 66(h) and 75(2) corrected to element changes (correct withholds); verifier prompt names the dropped-limitation case (probe gate 24/24 caught, 0/22 withheld, 3 draws); understand prompt names the function-less description (vague items 3/3, off-topic and legal 0/3). Three full clarify draws: every absolute gate 0, every value gate by majority (triage 3/3, vaguest item 3/3). On-topic: 0 leaks, faithfulness and citation accuracy held. `AGENTIC_RAG` still off in production.
- **ADR-33** — **BUILT, FLAG OFF (23 Sep 2026): a recital-to-provision map replaces the ADR-32 demotion behind `RECITAL_MAP`.** 157 edges in `provision_reference` (54 explicit from the recitals' own citations across 29 recitals, 103 semantic at one high-confidence link per recital; 132 of 180 recitals linked). With the flag on both retrieval legs exclude recitals and at most two linked recitals are placed behind the operative slice, only when their provision is served, re-chosen after the grader's cut. Full gate: every absolute gate 0, all four "why" items ground on recital plus operative provision, recall equal, faithfulness up, but citation accuracy on shared items 0.907 to 0.837 because two marginal direct items abstain under the longer context (measured systematic, cause is generator marginality, two fixes rejected). Flag stays off pending Yash's pick among the options in the ADR.
- **ADR-32** — **ACCEPTED (23 Sep 2026): the 180 recitals in the corpus as explanatory, non-binding passages.** Source: original OJ act CELEX 32024R1689 (12.7.2024), hand-fetched, SHA-256 recorded; one row (`rec_N`) and one chunk per recital with the prefix "Recital N (explanatory, non-binding)". A recital is never the rule: system-prompt rule, deterministic verifier check (recital cited with no article or annex = misgrounded, regenerate, then abstain), and a retrieval demotion (first 5 slots operative, at most 2 recitals per slice; swept, cap 2 / head 5 chosen). Four "why" golden items ground on recital plus operative provision. Full gate numbers in the ADR.
- **ADR-30** — **ACCEPTED (23 Sep 2026): injection guard judges whom the verb is aimed at.** The ADR-23 guard false-blocked "Can it change the classification rules too?" in 4 of 12 draws. New 30-message probe set (12 attempts incl. indirect forms, 18 innocent trigger-word follow-ups), gate non-compensatory: before, 11/12 attempts blocked and 2/18 follow-ups false-blocked; after, 12/12 and 0/18 over six draws. No keyword list; the prompt names the addressee.
- **ADR-29** — **ACCEPTED (23 Sep 2026): Annex I ingested as the first sectioned annex.** Citation scheme `anx_<annex>.sec_<section>.pt_<n>` for sectioned annexes only (Annex III unchanged); section rows carry the section heading; the M1 deletion of item 1 is a row with the marker and no text (no chunk), item 21 carries M1; labels render "Annex I, Section A, point 2" and the verifier parses them back. 24 rows, 20 chunks (1,136 to 1,156), embedded only those, BM25 rebuilt, structure map lists the sections. Three known items rank first on both legs. Golden item added for the lift safety-component route.
- **ADR-28** — **ACCEPTED (23 Sep 2026): single-paragraph article bodies restored to the corpus.** Eight articles (32, 39, 85, 87, 94, 102 to 104) had only their heading stored; the parser now keeps a bare body on the article row, the chunker treats a childless article as a leaf labelled "Article N", and a dry-run-first backfill added 8 chunks (1,128 to 1,136), embedded only those, rebuilt BM25. 119/119 articles retrievable; the Article 32 and 85 phrases rank first on both legs. Six annexes (I, VII, VIII, X, XI, XIV) still pending a parser: scope below.
- **ADR-27** — **BUILT, flag DEFERRED (23 Sep 2026): risk-tier framing behind `RISK_TIER_FRAMING`.** Tiered understand terms (retrieves the transparency provision on the first pass, 12/12) and a scope-sorted explain instruction (covers / adjacent / unrelated), no provision id in the logic. 14-item risk-tier set, 3 draws: absolute gates all 0 (leaks, stretches, out-of-context citations, high-risk regression, property valuation), value gates failed: transparency 3 of 4 items, not-listed 0 of 4 (the adjacent rule that protects property valuation also silences the spam filter), copilot item still abstains with the covering provision first in context. On-topic citation accuracy 0.868 to 0.842 on one item. Off until the not-listed rule is redesigned.

## 17. Deferred / To-Verify register
*Single place for everything we consciously postponed, so no chat loses it. The files remember; nothing else does. Review this section at the start of each new phase.*

**Deferred decisions (settled we'd wait — logged as ADRs):**
- **ADR-6** — exact article-reference lookup (query citation-pattern → direct `citation_id` lookup). Deferred until eval quantifies need.
- **ADR-7** — **CLOSED. Hybrid shipped** (see §16). No longer an open fork.

**Operational gaps from shipping hybrid retrieval (20 Sep 2026):**
- **`build_bm25_index.py` MUST run on every deploy and after every re-ingest.** If it doesn't, production silently serves `vector_only_degraded` — correct answers, but vector-only quality. **Enforced since 21 Sep 2026:** `backend/railway.json`'s start command runs it before uvicorn on every instance boot (the index is gitignored and the filesystem is ephemeral, so it cannot ship in the image). Still manual after a local re-ingest.
- **The missing-index warning fires PER REQUEST.** Deliberate (a missing index degrades all traffic, so it should be loud), but it will be noisy in that state. Revisit the cadence once real log aggregation exists.
- **5 of 7 flagged `golden_set_realistic.yaml` labels are still unverified against EUR-Lex.** Until then the weight-0.6 decision rests on LLM-generated labels. All three eval sets are LLM-generated; none is human-authored, so they may share a blind spot the way the first two shared the heading one.
- **`load_index` caches per process** — a rebuilt index is NOT picked up until restart. A deploy that rebuilds the index without restarting the app keeps serving the old one.

**Deferred from the breadth/slice change (21 Sep 2026, ADR-8):**
- **Deterministic actor/article field from `citation_id`** to filter or down-weight wrong-actor passages. Contamination sits at ~6 and ADR-8 did not move it. *Next tight loop.*
- **`config.py` daily-quota recalibration** — per-call cost roughly tripled at slice 15, and the current limits were calibrated against a 5-chunk context. **Before public deploy.**
- **`run_eval.py` `RETRIEVAL_DEPTH` realignment** to the production breadth constant, so the harness can actually see the parameter it validates. Also fix the stale docstring claiming fetch-10-then-slice-5 equals fetch-5 — false whenever `min_similarity > 0`, because the filter is applied after the SQL `LIMIT`.
- **Full judged before/after guard for the breadth/slice change**, once the OpenAI budget is topped up. ADR-8 shipped on retrieval-only validation plus a static wiring proof.

**Deferred from the actor prior (21 Sep 2026, ADR-10):**
- **`used_contamination` generation confirmation for the actor prior**, run alongside the ADR-8 judged guard at budget top-up. Bounded to the 5 enumeration queries; not needed to ship because `used_contamination <= ctx_contamination`, which is now 0.
- **Broaden the actor map** (e.g. `art_43` conformity assessment, `art_48` CE marking, `art_73` serious incidents) **only if future queries implicate them.** They are `None` by design in phase 1: substantively provider duties, but no paragraph names the provider as subject, so the deterministic evidence is weaker and no measured query needed them.

**Deploy prerequisites and test hygiene (21 Sep 2026, ADR-11):**
- **Deploy checklist (Railway backend, Vercel frontend; full runbook in README `## Deploy`).** `backend/railway.json` runs `alembic upgrade head` as the pre-deploy command (before the new instance starts) and `build_bm25_index.py` at the head of the start command. Order matters for the migration: `_write_trace_safe` swallows failures, so code writing the `environment` column against a table that lacks it fails silently, and every uncounted call is an open quota with no error anywhere. Railway variables: `DATABASE_URL` (session pooler URL), `OPENAI_API_KEY`, `INTERNAL_API_SECRET`, `APP_ENV=production`. Smoke: `/health` reads `"environment": "production"`, `/docs` is 404, unauthenticated `/ask` and `/classify` are 401, and the first real turn's `query_trace` row shows `environment='production'` with `retrieval_config` starting `hybrid_bm25`.
- **DONE (21 Sep 2026): live-stack tests gated behind `RUN_LIVE_TESTS=1`.** The five tests that hit real Supabase and real OpenAI (`test_ask_api`, `test_bm25`, `test_generation`, `test_judge`, `test_search`) are marked `@pytest.mark.live` and skipped by `conftest.py` unless the variable is set. Measured cost when opted in: 3 chat-model calls + 3 embedding calls (~$0.02) per run. A plain `pytest` now makes zero paid calls even with a key present (verified: 0/0 on the counter, 115 passed / 5 skipped, zero DB row delta).

**Deferred from the assessment wedge (21 Sep 2026, ADR-12 to ADR-14):**
- **Deploy prerequisite:** migration `6aa3cd421b84` (the `assessment` table) must run **before** the backend code that writes it deploys (the ADR-11 rule; `railway.json`'s pre-deploy step does this, but a manual deploy must not skip it).
- **Immutable snapshots of the quoted text.** Saved assessments and their exports re-render provision text from the current corpus. Recorded as a known limitation in ADR-13/14 and in the UI and document footer; decide later whether to snapshot the rendered `ProvisionText` at save time.
- **`ENGINE_MAJOR` discipline.** The rules hash covers rule data, not engine logic; a control-flow change in `engine.py` needs a hand bump. Consider a test that pins the engine's decision table so a logic change fails loudly.
- **Server-generated PDF** (ADR-14 option A), only if a customer needs a PDF we produce rather than one they print; feed the existing renderer's output to an engine.
- **`ClassificationRun` in `app/db/models/audit.py` is dead code** from the five-rule classifier: never written, unrelated to the `assessment` table. Remove in a cleanup pass with its own tiny migration.
- **Annex I ingestion** so the Article 6(1) product route can be grounded rather than reported as incomplete (ADR-004 gap).
- **Public or anonymous access to the assessment** as the free funnel the strategy doc wants; today it stays behind sign-in because opening it changes the ingress-hardening posture.
- **LLM plain-language layer and free-text input**: separate change, eval-gated and budget-gated per CLAUDE.md invariant 3.

**Roadmap from the prototype spree (22 Sep 2026; prototypes A and B live behind `NEXT_PUBLIC_PROTOTYPES=1`):**
- **Route definitional chat questions to the free Act glossary.** "What is a deployer?" costs a paid retrieval today; the Act navigator answers it from Article 3 verbatim at no cost. Cheap: detect "what is / who is <term>" against the 70 defined terms in `is_trivial_input`'s neighbourhood and return the definition with its citation as a scope-style turn. Deterministic; no gate needed beyond a test that the term match is exact.
- **Change watch between corpus versions.** When the consolidated text is re-ingested, list the provisions a saved record quotes that changed (text diff by citation id) and mark the record. Needs a second `corpus_version` row and a diff; the single biggest trust feature the GRC market articles describe (records go stale). Not buildable until an amendment is ingested.
- **Evidence scaffold per obligation.** For each obligation group, the sub-provisions that spell out the artefact (Article 11 -> Annex IV items, Article 17 -> its listed aspects), quoted, as a checklist. A reviewed map like the obligation table: every row read against the text before it ships.
- **Portfolio view** of all saved assessments: headline, roles, next application date (from the timeline builder), engine version, corpus date. List endpoint exists.
- **Shareable read-only record link** (signed, expiring, revocable) for counsel. Security review before design: no-leak rules apply to the token, not just the id.
- **Machine-readable export** (JSON, OSCAL-shaped) for GRC import. Build when a buyer names the target system.
- **Citation-verifier API**: is this quote verbatim in the Act, and where. Substring search over provisions; a partner-channel feature.
- **Agentic RAG follow-ups (ADR-20, 22 Sep 2026):** (a) DSPy or equivalent prompt tuning of the sub-steps (rewrite, grade, verify, plan, compose) against the agentic set and the probe set, gated the same way; every prompt today is hand-written and measured once. (b) Verifier: done as far as measurement allows (ADR-25): gpt-4o with passage headings is the verifier, 0 false accepts on 22 traps over 3 draws; the Article 66(h) paraphrase is still withheld and on re-reading may be a modality change rather than a paraphrase (Yash to rule on the probe gold). (c) A UI progress affordance for agentic turns (which node is running, 5 to 15 s) before `AGENTIC_RAG` goes on in production. (d) Skip the grader's widen when the top vector similarity is far below the anchor floor, saving about 5 s on off-topic turns; sweep the constant first. (e) Trace columns for grader and verifier tokens so the audit log carries the whole spend. (f) Confirm the two flagged multi-hop gold items (ag_mh_02 chapeau vs points, ag_mh_06 wording vs Article 6(3)).
- **ADR-23 follow-up: injection-guard false blocks. Done (ADR-30).** The guard prompt now tests whom the verb is aimed at; 0 of 18 innocent trigger-word follow-ups blocked and 12 of 12 attempts blocked over six draws. Re-run `python evals/run_guard_eval.py --repeats 3` after any guard change.
- **ADR-004 Step B (23 Sep 2026): Annex I done (ADR-29), five annexes remain.** The pattern is set: one parser per layout, `anx_<annex>.sec_<section>.pt_<n>` where sections exist, `scripts/backfill_annex.py <annex>` to add it. Remaining, none matching the grid-list or the numbered-paragraph parser: Annex VII (conformity assessment based on QMS and technical documentation): five numbered sections, bare paragraphs with decimal sub-numbers ("3.1.") and grid lists beneath them. Annex VIII (registration information): three lettered sections (A, B, C), unnumbered bare paragraphs and 25 grid points. Annex X (large-scale IT systems): seven numbered sections each holding bare paragraphs naming Regulations. Annex XI (GPAI technical documentation): two sections whose titles span two title lines, bare paragraphs and 13 grid points. Annex XIV (notification codes): six HTML tables of `tbl-norm` cells with footnotes; a table parser, not a list parser. Suggested order: I first (the product-safety high-risk route, 20 list items, needs section plus marker handling), then VIII and XI (grid lists under sections, closest to the existing parser), then VII and X, and XIV last or as a table-to-text special case. Citation scheme to decide before building: `anx_I.sec_A.pt_2` or `anx_I.pt_2` with the section as heading; the structure map and `citation_label` must render whichever is chosen.
- **ADR-27 follow-ups (risk-tier framing, flag off).** (a) Redesign the not-listed rule so a spam filter gets the honest "none of the retrieved provisions names this use, the AI-literacy obligation applies" answer while property valuation still routes: define ADJACENT narrowly (same area of use named by the provision) or move the adjacency test out of the prompt into a deterministic check on the retrieved labels' areas; measure both buckets together. (b) The copilot description abstains 3/3 with the transparency provision at fused rank 0; probe the generator on that single context with instruction variants before touching the shared instruction. (c) Decide whether a camera system "interacts directly with natural persons"; the verifier accepts the citation. (d) Re-run `AGENTIC_RAG=1 CLARIFY_FOLLOWUP=0 RISK_TIER_FRAMING=1 python evals/run_risk_tier_eval.py --repeats 3` and the on-topic set; flip on absolute 0 and value majority with citation accuracy held.
- **ADR-26 follow-ups.** (a) The clarify eval reports single draws; the split gate was computed by a scratch aggregator over three runs. Fold `--repeats` and the majority/absolute split into `evals/run_intent_eval.py --clarify` so the gate is one command. (b) The drift bucket shows that any message mentioning AI in a product now enters explain mode and may be asked what the system does; watch real traffic for follow-ups fired on messages that were not about a system. (c) The variance seen per draw (understand, verifier, guard, decompose) argues for a repeat count on every eval runner and for reporting per-draw counts rather than one run.
- **ADR-21 follow-ups.** Decided: chat never stretches to a closest provision for a use the Act does not name. Remaining: the shop-chatbot item is understood with Article 50(1) retrieved and still abstains, the spam-filter item does not retrieve Article 4 (its gold is a judgement); both are candidates for the explain-step prompt tuning (DSPy) on the plain_language bucket with the leak gate. Confirm the flagged gold (spam filter to Article 4, shop facial recognition to Annex III 1(a)).
- **Prototype B follow-up:** the timeline's route rule (Annex III vs Annex I date) is implemented; still to decide whether the timeline joins the record page or stays a separate view.

**Deferred build work:**
- **Persist the assembled prompt string and the raw model completion** for debugging. Today `retrieval_trace` stores the chunks plus a used flag, and `query_trace`/`message`/`citation` store the answer, so the exact text sent to the model is not recoverable after the fact.
- **Conversation persistence in the UI** — list and resume past chats. The data already exists in `chat_session`/`message`; only the frontend surface is missing. Optional follow-on: multi-turn context memory.
- **Multi-turn chat follow-ups (Part B): BUILT, FLAG OFF (ADR-19, 22 Sep 2026); superseded inside the graph by the rewrite node with dual retrieval (ADR-20), on when `AGENTIC_RAG=1`.** Query rewrite on turn 2+ behind `FOLLOWUP_REWRITE`; passed the hard gates, missed the value gate (+12 vs +30 points of correct citation). Re-run `evals/run_followup_eval.py` after any retrieval change; enable only on a passing run. Remaining idea from the original note (pass the last N turns to generation) is not built.
- **Jev advisory reranker / verification-layer experiment** — gated behind the deterministic actor tag above, benchmarked on our corpus against cross-encoder and open-weights alternatives (see **ADR-9**).
- **Reranker — v2 experiment, gated on the heading-aware eval.** LegalBench-RAG found general rerankers can *hurt* on legal text, so this only ships if `golden_set_realistic.yaml` proves lift. Do not add it on general-purpose reputation.
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
