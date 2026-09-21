"""Stage 3: sweep the RRF lexical weight for hybrid_bm25. Measurement only.

Stage 2 showed BM25 finds gh_13 and gh_16 (the two hard entries vector-only
misses) at rank 1, but hybrid_bm25 discards both: with vector 0.7 / lexical 0.3
and k=60, a document absent from vector's top-10 scores at most 0.3/61 =
0.00492, below every vector hit. This sweeps that weight to find where the
trade actually sits.

Retrieval is done ONCE per question and re-fused per weight - vector and BM25
results don't depend on the weight, only the fusion does. That turns a 5x
embedding bill into 1x.

    python -m evals.sweep_weights            # easy set (golden_set.yaml)
    python -m evals.sweep_weights --hard     # hard set, per category
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import CorpusVersion
from app.db.session import SessionLocal
from app.retrieval.bm25_index import load_index
from app.retrieval.search import bm25_search, rrf_rank_and_fuse, vector_search
from evals.run_eval import (
    GOLDEN_SET_HARD_PATH,
    GOLDEN_SET_PATH,
    RANK_CUTOFF,
    RETRIEVAL_DEPTH,
    load_golden_set,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

LEXICAL_WEIGHTS = [0.3, 0.4, 0.5, 0.6, 0.7]

# The two hard entries BM25 ranks #1 but RRF discarded at lexical_weight=0.3.
WATCHED_IDS = ("gh_13", "gh_16")


def collect_retrievals(session, golden_set: list[dict], corpus_version_id: int):
    """One vector + one BM25 retrieval per question, reused for every weight."""
    collected = []
    for item in golden_set:
        if item["expected_abstention"]:
            continue
        vector_results = vector_search(
            session,
            item["question"],
            corpus_version_id,
            top_k=RETRIEVAL_DEPTH,
            min_similarity=0.0,
        )
        bm25_results = bm25_search(
            session, item["question"], corpus_version_id, top_k=RETRIEVAL_DEPTH
        )
        collected.append((item, vector_results, bm25_results))
    return collected


def _metrics(retrieved_ids: list[str], expected: str) -> tuple[float, float, float]:
    return (
        recall_at_k(retrieved_ids[:RANK_CUTOFF], expected),
        reciprocal_rank(retrieved_ids[:RANK_CUTOFF], expected),
        ndcg_at_k(retrieved_ids, expected, k=RETRIEVAL_DEPTH),
    )


def _mean(rows: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    if not rows:
        return 0.0, 0.0, 0.0
    n = len(rows)
    return (
        sum(r for r, _, _ in rows) / n,
        sum(rr for _, rr, _ in rows) / n,
        sum(nd for _, _, nd in rows) / n,
    )


def evaluate(collected, lexical_weight: float | None):
    """lexical_weight=None evaluates the vector_only reference."""
    by_category: dict[str, list[tuple[float, float, float]]] = {}
    overall: list[tuple[float, float, float]] = []
    ranks: dict[str, int | None] = {}

    for item, vector_results, bm25_results in collected:
        if lexical_weight is None:
            retrieved_ids = [r.citation_id for r in vector_results]
        else:
            fused = rrf_rank_and_fuse(
                vector_results,
                bm25_results,
                vector_weight=1.0 - lexical_weight,
                lexical_weight=lexical_weight,
                top_k=RETRIEVAL_DEPTH,
            )
            retrieved_ids = [f.result.citation_id for f in fused]

        expected = item["expected_citation_id"]
        m = _metrics(retrieved_ids, expected)
        overall.append(m)
        by_category.setdefault(item.get("category", "all"), []).append(m)
        if item["id"] in WATCHED_IDS:
            ranks[item["id"]] = next(
                (i + 1 for i, cid in enumerate(retrieved_ids) if cid == expected), None
            )

    return by_category, overall, ranks


def _fmt(label: str, n: int, m: tuple[float, float, float]) -> str:
    recall, rr, ndcg = m
    return f"{label:<16}{n:<5}{recall:<11.3f}{rr:<9.3f}{ndcg:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hard", action="store_true", help="Use golden_set_hard.yaml.")
    args = parser.parse_args()

    path = GOLDEN_SET_HARD_PATH if args.hard else GOLDEN_SET_PATH
    golden_set = load_golden_set(path)

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
        if load_index(latest.id) is None:
            print(
                f"No bm25 index for corpus_version {latest.id} - build it with "
                "scripts/build_bm25_index.py",
                file=sys.stderr,
            )
            sys.exit(1)

        collected = collect_retrievals(session, golden_set, latest.id)
        print(f"set: {path.name}   answerable questions: {len(collected)}")
        print(
            "candidate breadth: 10 (held fixed - breadth is a separate lever), k=60\n"
        )

        base_by_cat, base_overall, base_ranks = evaluate(collected, None)

        print("=== vector_only reference ===")
        print(f"{'category':<16}{'n':<5}{'recall@5':<11}{'mrr':<9}ndcg@10")
        for category in sorted(base_by_cat):
            print(
                _fmt(category, len(base_by_cat[category]), _mean(base_by_cat[category]))
            )
        print(_fmt("ALL", len(base_overall), _mean(base_overall)))

        results = {}
        for weight in LEXICAL_WEIGHTS:
            results[weight] = evaluate(collected, weight)

        categories = sorted(base_by_cat)
        for category in [*categories, "ALL"]:
            print(f"\n=== hybrid_bm25 sweep - {category} ===")
            print(f"{'lexical_w':<11}{'vector_w':<11}{'recall@5':<11}{'mrr':<9}ndcg@10")
            for weight in LEXICAL_WEIGHTS:
                by_cat, overall, _ = results[weight]
                rows = overall if category == "ALL" else by_cat[category]
                recall, rr, ndcg = _mean(rows)
                marker = "  <- current" if weight == 0.3 else ""
                print(
                    f"{weight:<11.1f}{1 - weight:<11.1f}"
                    f"{recall:<11.3f}{rr:<9.3f}{ndcg:.3f}{marker}"
                )

        watched = [i for i in WATCHED_IDS if i in base_ranks]
        if watched:
            print("\n=== watched entries (BM25 finds, RRF discarded at 0.3) ===")
            print(
                f"{'entry':<9}{'vector_only':<13}"
                + "".join(f"w={w:<8.1f}" for w in LEXICAL_WEIGHTS)
            )
            for gid in watched:
                cells = []
                for weight in LEXICAL_WEIGHTS:
                    rank = results[weight][2].get(gid)
                    cells.append(f"{rank if rank else '-':<10}")
                base = base_ranks.get(gid)
                print(f"{gid:<9}{(base if base else '-'):<13}" + "".join(cells))
            print(
                "('-' = not retrieved in the top 10; top-5 membership is what Recall@5 counts)"
            )
    finally:
        session.close()


if __name__ == "__main__":
    main()
