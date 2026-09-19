# Architecture Decision Log
One entry per non-obvious decision: what, why, alternatives rejected. Newest at top.

## ADR-7: Lexical retrieval is currently inert on real queries; calibration deferred to eval phase (2026-09-18)
Context: websearch_to_tsquery AND-joins all terms by default. Across every real query
tested (step 22 "Article 6(2)", step 23 control "credit scoring high risk", 3 off-topic
calibration queries), lexical search returned 0 results; vector search carried all retrieval.
The hybrid/RRF code is correct but dormant on real input.
Decision: Do NOT switch to OR-joining or plainto_tsquery reactively. Defer lexical
calibration to the eval phase, where a golden set will measure whether lexical actually
lifts recall/MRR and justify the query-processing choice with numbers.
Status: Deferred. Revisit with the eval harness.

Update (2026-09-19) — Wave 1 eval harness delivered the awaited evidence: a golden
set built specifically to favor lexical (4 questions on rare, verified verbatim
phrases - "subliminal techniques", "biometric categorisation system", "fundamental
rights impact assessment", "quality management system") still produced zero rank
contribution from keyword_search across all 4. Root-caused directly: keyword_search
returned 0 results for all 4, because websearch_to_tsquery AND-joins every stemmed
word in a full natural-language question (15-20 words), not just the distinctive
phrase - requiring all of them to co-occur in one short chunk is essentially
impossible regardless of how distinctive the target phrase is.
Decision: This is now a decided fork, not an open question - the lexical half as
currently built adds nothing, and the cause is query construction, not corpus
content or phrase rarity. Two options recorded for a future step (neither
implemented now):
  (a) Fix query construction - extract key terms / OR-join before
      websearch_to_tsquery, so a question's distinctive terms can match without
      requiring every scaffolding word to co-occur too.
  (b) Drop the lexical half and ship an honest vector-only retriever, removing
      the dead-weight complexity of a hybrid path that never contributes.
Status: Decided (lexical as built is inert; cause is query construction, not
corpus). Choice between (a) and (b) deferred to a later step.

## ADR-006: Exact article-reference lookup is deferred to a dedicated structured path (2026-09-18)
Context: Integration testing showed "Article 6(2)" returns zero lexical results
(websearch_to_tsquery AND-splits "6(2)"; the reference lives in citation_id
metadata, not chunk_text). Hybrid retrieval solves conceptual queries, not exact
reference lookup.
Decision: Do NOT patch websearch_to_tsquery (e.g. OR-joining terms) to force a
match. Defer a dedicated reference-lookup path (detect citation pattern in query →
direct citation_id lookup) until the eval harness quantifies how often it's needed.
Status: Deferred. Revisit after golden-set exact-reference questions are graded.

## ADR-005 — Host database on Supabase (managed Postgres + pgvector) (2026-09-16)
Decision: Move from local Docker Postgres to Supabase (managed Postgres 16 + pgvector) for development. DB TYPE is unchanged — Supabase IS Postgres + pgvector; this is a hosting choice, not an architecture change.
Why: Visual table browser aids learning/inspection; same platform used in prior RAG project; cloud DB is where we'd deploy anyway. All code reads DATABASE_URL from .env, so the switch is a connection-string change.
Rejected: local Postgres + a GUI tool (valid, but chose Supabase's integrated UI + cloud-ready now). Pure vector DB (Pinecone/Qdrant) — wrong for our relational + filtering + transactional needs (see ADR rationale / interview Scenario 4).
Note: keep docker-compose.yml for offline fallback; migrations + ingestion must be re-run against Supabase.

## ADR-004 — Ingest safe subset first; defer 6 structurally-different annexes (2026-09-16)
Decision: Ingest 119 articles + 8 structurally-compatible annexes (II, III, IV, V, VI, IX, XII, XIII) now via an explicit UNSUPPORTED_ANNEXES exclusion. Build the end-to-end pipeline (chunk→embed→retrieve→copilot) on this. Add annexes I, VII, VIII, X, XI, XIV later (Step B: new section-structure parser) via re-ingestion.
Why: Get the full system proven on real data sooner; the excluded annexes use a different layout (numbered sections/decimal sub-numbering) needing a new parser capability. Gap is explicit, logged, visible on every run, and outside the v1 financial-services flagship. Corpus versioning makes re-ingestion clean.
Rejected: Path B (finish all annexes before any downstream work) — delays proving the higher-risk unknowns (retrieval quality, citation precision).
Known limitation: Annex I (product-safety high-risk route) not in corpus until Step B. Pending: Step B parentage-verified section parser.

## ADR-003 — unstructured.io reserved for v3 PDF-only corpora (2026-09-16)
Decision: Parse structured HTML directly for the AI Act (v1). Reserve an unstructured.io + summarize-visuals pipeline for v3 corpora (recitals, Irish national layer) IF those are PDF-only / contain tables or images.
Why: AI Act source is clean structured HTML with machine-readable IDs and no visual tables/images — direct parsing gives exact citations; unstructured.io would flatten structure then re-guess it.
Rejected: unstructured.io/PDF pipeline for v1 (throws away ground-truth structure; multimodal machinery unused on text-only source).

## ADR-002 — Free-standing sentences not captured as provisions (2026-09-16)
Decision: v1 parser captures articles, paragraphs, points, annex points/sub-points. Deeper nesting and free-standing sentences (e.g. Article 6 "Notwithstanding…") are preserved in parent text but not independently citable.
Why: Scope control; flagship cases (credit scoring) are covered.
Risk to monitor: verify at retrieval time that no legally-important text is silently un-retrievable (poisoned-index guard).

## ADR-001 — EUR-Lex WAF requires manual-fetch fallback (2026-09-16)
Decision: fetch_corpus.py uses a plain fetch; if EUR-Lex serves an AWS WAF challenge, fall back to manual browser download. Never script around the WAF.
Why: Bot-evasion is off-limits; provenance is preserved via content_hash regardless of fetch method.
Monitored signal: sha256 diff on re-fetch detects source change.