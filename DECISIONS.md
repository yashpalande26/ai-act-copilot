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

Update (2026-09-20) — Stage 0 of the BM25 work built a discriminating eval set
(evals/golden_set_hard.yaml, 41 entries: 23 exact_term, 12 control, 6 abstention)
via evals/build_golden_set_hard.py, and it produced two findings that bear
directly on the (a)/(b) fork above.

1. Hard-tier lexical floor is zero. Every one of the 23 hard entries - each one a
question where vector-only ranks the gold provision at 2+ or misses it entirely -
returns 0 rows from keyword_search. Not "ranked poorly": zero rows. This reproduces
the 2026-09-19 finding on a larger, purpose-built, harder set rather than on 4
hand-picked questions, and confirms the AND-join diagnosis is the mechanism.
Consequence for measurement: on the hard tier the lexical baseline is exactly
0.000, so any Stage 1 lift is attributable to fixing query construction, not to
BM25's scoring function per se. Caveat recorded honestly: during the build, 1 of
the 25 hard candidates ("any refusal, restriction, suspension or withdrawal of a
Union technical documentation assessment certificate...") DID retrieve gold
lexically - a rare, contiguous phrase surviving the AND-join. That entry was
removed in human review for label ambiguity (gold and its rank-1 distractor were
near-identical adjacent points), not because of its lexical behaviour. So the
mechanism is overwhelmingly dominant but not absolute.

2. Negative result: near-duplicate provisions do NOT break vector search. One
standing argument for keeping lexical was that semantically near-identical sibling
provisions would confuse embeddings. Tested directly: 57 near-duplicate candidates
(difflib ratio > 0.5 within a parent), each given a question generated with the
target AND its confusable siblings in the prompt, instructed to turn on the detail
that distinguishes them. 39 passed the question-quality screen and reached
retrieval; 37 of those 39 (95%) were ranked #1 by vector-only. Only 2 survived the
rank filter and both then failed the discrimination screen. The near_duplicate tier
is therefore shipped DECLARED EMPTY - the category is retained in the schema and
the builder so the negative result stays visible, rather than deleted as if never
attempted. Interpretation: once a question actually names the distinguishing
detail, semantic search handles near-duplicates correctly; the earlier probe's
apparent failures were vague questions whose near-twin answered them equally well,
i.e. broken labels rather than retrieval weakness.
Consequence for the fork: this removes one of the motivations for option (a). It
does not decide the fork - the hard tier still shows vector-only failing 23 real
questions that lexical currently cannot help with at all.
Status: unchanged - still Decided that lexical as built is inert; choice between
(a) and (b) still deferred, now with a measuring instrument that can tell them
apart per-category.
Caveat on that instrument: the hard tier is selected adversarially against
vector-only, so vector-only's weak showing on it is a property of the sampling,
not a finding; the control tier is biased the opposite way (selected at vector
rank 1). Report per-category, never pooled.
Correction (2026-09-20, same day): an earlier draft of this paragraph said
vector-only scores "~0" on the hard tier. That is wrong as written and is
corrected here. What is 0 by construction is vector-only's *rank-1 precision*
(0 of 23 hard entries put gold first). Recall@5 is 0.870, because the hard tier
admits gold at ranks 2-5 - it excludes rank 1, not the whole top-5. Measured
baseline, hard tier, vector-only: Recall@5 0.870, MRR 0.335, nDCG@10 0.483.
The practical consequence is that Recall@5 has almost no headroom on this tier,
so a retrieval improvement shows up in MRR/nDCG rather than in Recall@5.

Update (2026-09-20, Stage 1) — The (a)/(b) fork above is now resolved with
measurements rather than argument: option (a) (fix query construction) was
implemented, measured on golden_set_hard.yaml, and REVERTED. Option (b) (drop
lexical) is not taken either. The lexical leg stays as-is on main, inert, until
Stage 2 (bm25s).

What was built: keyword_search's websearch_to_tsquery input was rewritten from
the raw question to an OR-joined string of its content words (alphanumeric
tokens, >=3 chars, minus the literal operator words or/and/not). The SQL,
ts_rank_cd ranking, GIN index, threshold (0.1) and function signature were all
unchanged - only the bound parameter differed. RRF weights were deliberately
left at 0.7/0.3 so the A/B isolated one variable.

Measured on the hard set (23 exact_term, 12 control), vector_only rows
byte-identical before/after, confirming only the lexical leg moved:
  hard tier  MRR        0.335 -> 0.590  (+76%)
  hard tier  nDCG@10    0.483 -> 0.682  (+41%)
  hard tier  gold at rank 1   0/23 -> 11/23
  hard tier  Recall@5   0.870 -> 0.783  (regression)
  control    Recall@5   1.000 -> 0.917  (regression)
  control    MRR        0.958 -> 0.917  (regression)
  default golden_set.yaml, hybrid MRR  0.896 -> 0.854  (regression)
Note the control-tier hybrid baseline was already 0.958 MRR, not 1.000: even the
inert lexical leg was perturbing one control question before any change.

Root cause of the regressions, diagnosed on the worst case (gh_27, "What
determines the duration of participation in the AI regulatory sandbox?"): the OR
query is dominated by "sandbox"/"regulatory", which match dozens of Article 57
chunks, so the lexical leg returns 10 topical-but-wrong rows and misses gold
entirely. Five of those also appear in vector's top-10, and RRF's "present in
both lists" bonus (>=0.01458) outranks gold's vector-only score (0.01148),
pushing a correct rank-1 result down to rank 6. OR-joining trades precision for
recall, and RRF amplifies lexical's false positives whenever it is confidently
wrong.
The deeper cause is that ts_rank_cd has no IDF term: it cannot know that
"sandbox" is common in this corpus while "duration" is rare, so it cannot
down-weight the words that make the OR query noisy.
Decision: revert the OR-join on main (the easy-case regression is not worth the
hard-case gain), keep the Stage 1 eval infrastructure (--hard, --retrieval-only,
per-category table, nDCG@10), and treat this as measured motivation for Stage 2:
BM25's IDF weighting is precisely the missing mechanism, and these numbers are
the baseline it must beat. Not attempted here and still open: tuning the RRF
lexical weight down from 0.3, which would blunt the false-positive amplification
but is a second variable.
Status: (a) implemented, measured, reverted. Lexical remains inert on main by
choice, with the reason now quantified rather than assumed. Stage 2 (bm25s) is
the next step.

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