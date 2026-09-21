"""Stage 4 investigation: sweep candidate breadth for hybrid_bm25 @ weight 0.5.

Stage 4 wiring surfaced a gh_27-style failure on a real out-of-sample query:
art_16.pt_a ("Obligations of providers of high-risk AI systems") sits at vector
rank 4 but is absent from BM25's top-10, so it loses its top-5 slot to chunks
that collect RRF's "present in both lists" bonus. Breadth is the untested lever
- a wider BM25 pool might contain art_16.pt_a and restore it.

This sweeps breadth over both legs simultaneously and reports the golden sets
(regression guard) alongside the out-of-sample probe (the actual symptom).

Retrieval is done ONCE per query at the maximum breadth and sliced; verified
exact, since both legs are deterministic ordered retrievals and a wider LIMIT
is a superset of a narrower one.

    python -m evals.sweep_breadth
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import CorpusVersion
from app.db.session import SessionLocal
from app.generation.answer import (
    RETRIEVAL_LEXICAL_WEIGHT,
    RETRIEVAL_VECTOR_WEIGHT,
)
from app.retrieval.search import bm25_search, rrf_rank_and_fuse, vector_search
from evals.run_eval import (
    GOLDEN_SET_HARD_PATH,
    GOLDEN_SET_PATH,
    RANK_CUTOFF,
    load_golden_set,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

BREADTHS = [10, 20, 30, 50]
MAX_BREADTH = max(BREADTHS)
MIN_SIMILARITY = 0.3  # generate_grounded_answer's production default

# The out-of-sample probe from the Stage 4 verification - realistic user
# questions, deliberately NOT in either golden set.
OUT_OF_SAMPLE = [
    "What obligations apply to providers of high-risk AI systems?",
    "What are the penalties for non-compliance with the AI Act?",
    "When does the AI Act apply to general-purpose AI models?",
    "What must a deployer do before using a high-risk AI system?",
    "Which AI practices are prohibited?",
    "What is required in the technical documentation?",
    "Who must register a high-risk AI system in the EU database?",
    "What transparency obligations apply to chatbots?",
]
FLAGSHIP_QUERY = OUT_OF_SAMPLE[0]
FLAGSHIP_EXPECTED = "art_16.pt_a"


def retrieve_max(session, query: str, corpus_version_id: int):
    """One retrieval per leg at MAX_BREADTH; slices serve every smaller breadth."""
    return (
        vector_search(
            session,
            query,
            corpus_version_id,
            top_k=MAX_BREADTH,
            min_similarity=MIN_SIMILARITY,
        ),
        bm25_search(session, query, corpus_version_id, top_k=MAX_BREADTH),
    )


def fuse_at(vector_results, bm25_results, breadth: int) -> list[str]:
    fused = rrf_rank_and_fuse(
        vector_results[:breadth],
        bm25_results[:breadth],
        vector_weight=RETRIEVAL_VECTOR_WEIGHT,
        lexical_weight=RETRIEVAL_LEXICAL_WEIGHT,
        top_k=breadth,
    )
    return [f.result.citation_id for f in fused]


def _mean(rows):
    if not rows:
        return 0.0, 0.0, 0.0
    n = len(rows)
    return (
        sum(r for r, _, _ in rows) / n,
        sum(rr for _, rr, _ in rows) / n,
        sum(nd for _, _, nd in rows) / n,
    )


def sweep_golden_set(session, path: Path, corpus_version_id: int, label: str) -> None:
    golden_set = [g for g in load_golden_set(path) if not g["expected_abstention"]]
    collected = [
        (item, *retrieve_max(session, item["question"], corpus_version_id))
        for item in golden_set
    ]

    print(f"\n=== {label} ({len(collected)} answerable) ===")
    print(f"{'category':<14}{'breadth':<9}{'recall@5':<11}{'mrr':<9}ndcg@10")

    categories = sorted({i.get("category", "all") for i, _, _ in collected})
    for category in [*categories, "ALL"]:
        for breadth in BREADTHS:
            rows = []
            for item, vector_results, bm25_results in collected:
                if category != "ALL" and item.get("category", "all") != category:
                    continue
                ids = fuse_at(vector_results, bm25_results, breadth)
                expected = item["expected_citation_id"]
                rows.append(
                    (
                        recall_at_k(ids[:RANK_CUTOFF], expected),
                        reciprocal_rank(ids[:RANK_CUTOFF], expected),
                        ndcg_at_k(ids, expected, k=10),
                    )
                )
            recall, rr, ndcg = _mean(rows)
            marker = "  <- current" if breadth == 10 else ""
            print(
                f"{category:<14}{breadth:<9}{recall:<11.3f}{rr:<9.3f}{ndcg:.3f}{marker}"
            )


def sweep_out_of_sample(session, corpus_version_id: int) -> None:
    collected = [
        (q, *retrieve_max(session, q, corpus_version_id)) for q in OUT_OF_SAMPLE
    ]

    print(f"\n=== out-of-sample probe ({len(collected)} realistic queries) ===")
    print(
        f"{'breadth':<9}{'queries dropping >=1 of vector top-5':<40}flagship recovers art_16.pt_a"
    )
    for breadth in BREADTHS:
        dropping = 0
        flagship_ok = False
        for query, vector_results, bm25_results in collected:
            vector_top5 = [r.citation_id for r in vector_results[:RANK_CUTOFF]]
            fused_top5 = fuse_at(vector_results, bm25_results, breadth)[:RANK_CUTOFF]
            if [c for c in vector_top5 if c not in fused_top5]:
                dropping += 1
            if query == FLAGSHIP_QUERY:
                flagship_ok = FLAGSHIP_EXPECTED in fused_top5
        marker = "  <- current" if breadth == 10 else ""
        print(f"{breadth:<9}{f'{dropping}/{len(collected)}':<40}{flagship_ok}{marker}")

    print("\n--- flagship query detail ---")
    query, vector_results, bm25_results = collected[0]
    print(f"query: {query}")
    bm25_rank = next(
        (
            i
            for i, r in enumerate(bm25_results, 1)
            if r.citation_id == FLAGSHIP_EXPECTED
        ),
        None,
    )
    vector_rank = next(
        (
            i
            for i, r in enumerate(vector_results, 1)
            if r.citation_id == FLAGSHIP_EXPECTED
        ),
        None,
    )
    print(f"  {FLAGSHIP_EXPECTED}: vector rank={vector_rank}  bm25 rank={bm25_rank}")
    for breadth in BREADTHS:
        top5 = fuse_at(vector_results, bm25_results, breadth)[:RANK_CUTOFF]
        print(f"  breadth {breadth:>2} fused top-5: {top5}")


def main() -> None:
    session = SessionLocal()
    try:
        latest = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        if latest is None:
            print("No corpus_version found.", file=sys.stderr)
            sys.exit(1)

        print(
            f"hybrid_bm25 @ vector={RETRIEVAL_VECTOR_WEIGHT}/"
            f"lexical={RETRIEVAL_LEXICAL_WEIGHT}, k=60, min_similarity={MIN_SIMILARITY}"
        )
        print(f"breadths swept: {BREADTHS}")

        sweep_golden_set(session, GOLDEN_SET_HARD_PATH, latest.id, "hard set")
        sweep_golden_set(session, GOLDEN_SET_PATH, latest.id, "easy set")
        sweep_out_of_sample(session, latest.id)
    finally:
        session.close()


if __name__ == "__main__":
    main()
