"""Enumeration tier: scores queries whose correct answer is a SET of citations.

Every existing eval scores a single expected citation (Recall@5, MRR, nDCG).
That is structurally blind to a "list" question: for "what obligations apply to
providers of high-risk AI systems?" the answer is all twelve points of Article
16, and a retriever that returns one of them scores a perfect 1.000 while the
answer is 1/12 complete. This tier measures set coverage instead.

Metrics, per query:
  context_recall  |gold INTERSECT final context slice| / |gold|   <- PRIMARY
  used_recall     |gold INTERSECT cited ids| / |gold|
  contamination   count of forbidden ids that were cited

context_recall is primary because it isolates RETRIEVAL. used_recall can only
be lower, since the model can cite nothing it was not given, so the gap between
the two separates a retrieval failure from a generation failure.

For every missing gold member the script also reports the fused rank it landed
at, probed deep enough to find it. That distinguishes the two failure modes
that look identical from the outside:
  rank <= breadth but > context slice  ->  the context slice cut it
  rank >  breadth                      ->  candidate breadth never saw it
  absent even at probe depth           ->  a genuine retrieval/indexing failure

Runs the SAME path /ask uses, at current production defaults. It reads those
constants rather than restating them, so it cannot silently drift from
production. It tunes nothing.

    python -m evals.eval_enumeration
"""

import inspect
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import AppUser, ChatSession, CorpusVersion
from app.db.session import SessionLocal
from app.generation.answer import (
    RETRIEVAL_CANDIDATE_BREADTH,
    RETRIEVAL_LEXICAL_WEIGHT,
    RETRIEVAL_VECTOR_WEIGHT,
    generate_grounded_answer,
)
from app.retrieval.search import bm25_search, rrf_rank_and_fuse, vector_search

SET_PATH = Path(__file__).resolve().parent / "golden_set_enumeration.yaml"

# Depth used ONLY to locate missing gold members for the diagnostic column.
# It does not affect any score; scoring uses production settings untouched.
PROBE_DEPTH = 300

# generate_grounded_answer's own defaults, needed here so the probe reproduces
# the same slice. Read off the signature rather than restated, so a production
# change to either default cannot silently desynchronise this eval from the
# config it claims to be measuring.
_SIG = inspect.signature(generate_grounded_answer).parameters
FINAL_CONTEXT_SIZE = _SIG["final_context_size"].default
MIN_SIMILARITY = _SIG["min_similarity"].default


def fused_ranks(session, question: str, corpus_version_id: int) -> dict[str, int]:
    """Fused rank of every citation_id at PROBE_DEPTH, using the production
    weights. Diagnostic only."""
    vector_results = vector_search(
        session, question, corpus_version_id, top_k=PROBE_DEPTH, min_similarity=0.0
    )
    bm25_results = bm25_search(session, question, corpus_version_id, top_k=PROBE_DEPTH)
    fused = rrf_rank_and_fuse(
        vector_results,
        bm25_results,
        vector_weight=RETRIEVAL_VECTOR_WEIGHT,
        lexical_weight=RETRIEVAL_LEXICAL_WEIGHT,
        top_k=PROBE_DEPTH,
    )
    ranks: dict[str, int] = {}
    for i, f in enumerate(fused, start=1):
        ranks.setdefault(f.result.citation_id, i)
    return ranks


def context_slice(session, question: str, corpus_version_id: int) -> list[str]:
    """The citation_ids that actually reach the prompt, reproducing
    generate_grounded_answer's retrieval exactly."""
    vector_results = vector_search(
        session,
        question,
        corpus_version_id,
        top_k=RETRIEVAL_CANDIDATE_BREADTH,
        min_similarity=MIN_SIMILARITY,
    )
    bm25_results = bm25_search(
        session, question, corpus_version_id, top_k=RETRIEVAL_CANDIDATE_BREADTH
    )
    fused = rrf_rank_and_fuse(
        vector_results,
        bm25_results,
        vector_weight=RETRIEVAL_VECTOR_WEIGHT,
        lexical_weight=RETRIEVAL_LEXICAL_WEIGHT,
        top_k=RETRIEVAL_CANDIDATE_BREADTH,
    )
    return [f.result.citation_id for f in fused[:FINAL_CONTEXT_SIZE]]


def main() -> None:
    entries = yaml.safe_load(SET_PATH.read_text())
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

        # Real FK chain, as the eval harness already does. Throwaway rows.
        user = AppUser(email="enum-eval@example.com")
        existing = (
            session.execute(select(AppUser).where(AppUser.email == user.email))
            .scalars()
            .first()
        )
        if existing is None:
            session.add(user)
            session.flush()
        else:
            user = existing
        chat = ChatSession(user_id=user.id, corpus_version_id=latest.id)
        session.add(chat)
        session.flush()
        session.commit()

        print(
            f"production config: breadth={RETRIEVAL_CANDIDATE_BREADTH}  "
            f"context_slice={FINAL_CONTEXT_SIZE}  "
            f"weights v={RETRIEVAL_VECTOR_WEIGHT}/l={RETRIEVAL_LEXICAL_WEIGHT}  "
            f"min_similarity={MIN_SIMILARITY}"
        )
        print(f"probe depth (diagnostic only): {PROBE_DEPTH}\n")

        rows = []
        details = []
        for e in entries:
            gold = list(e.get("gold") or [])
            forbidden = set(e.get("forbidden") or [])
            question = e["question"]

            ctx = context_slice(session, question, latest.id)
            result = generate_grounded_answer(
                session, question, latest.id, chat.id, write_trace=False
            )
            cited = [c.citation_id for c in result.citations]

            in_ctx = [g for g in gold if g in ctx]
            in_cited = [g for g in gold if g in cited]
            contamination = [f for f in forbidden if f in cited]

            rows.append(
                {
                    "id": e["id"],
                    "actor": e.get("actor", ""),
                    "n_gold": len(gold),
                    "context_recall": len(in_ctx) / len(gold) if gold else 0.0,
                    "used_recall": len(in_cited) / len(gold) if gold else 0.0,
                    "contamination": len(contamination),
                    "abstained": result.answer.startswith("I don't have enough"),
                }
            )

            missing = [g for g in gold if g not in ctx]
            ranks = fused_ranks(session, question, latest.id) if missing else {}
            details.append(
                {
                    "id": e["id"],
                    "question": question,
                    "cited": cited,
                    "contamination": contamination,
                    "missing": [(g, ranks.get(g)) for g in missing],
                }
            )

        print("=" * 104)
        print(
            f"{'id':<28}{'actor':<10}{'gold':<6}{'ctx_recall':<12}"
            f"{'used_recall':<13}{'contam':<8}abstained"
        )
        print("=" * 104)
        for r in rows:
            print(
                f"{r['id']:<28}{r['actor']:<10}{r['n_gold']:<6}"
                f"{r['context_recall']:<12.3f}{r['used_recall']:<13.3f}"
                f"{r['contamination']:<8}{r['abstained']}"
            )
        n = len(rows)
        print("-" * 104)
        print(
            f"{'MEAN':<28}{'':<10}{'':<6}"
            f"{sum(r['context_recall'] for r in rows) / n:<12.3f}"
            f"{sum(r['used_recall'] for r in rows) / n:<13.3f}"
            f"{sum(r['contamination'] for r in rows):<8}"
        )

        print("\n" + "=" * 104)
        print("PER-QUERY DETAIL")
        print("=" * 104)
        for d in details:
            print(f"\n{d['id']}")
            print(f"  question: {d['question']}")
            print(f"  cited   : {d['cited'] or '(none)'}")
            if d["contamination"]:
                print(f"  CONTAMINATION: {d['contamination']}")
            if not d["missing"]:
                print("  missing : none, full gold set reached the context")
                continue
            print(f"  missing from context ({len(d['missing'])}):")
            for cid, rank in d["missing"]:
                if rank is None:
                    verdict = f"NOT FOUND within probe depth {PROBE_DEPTH}"
                elif rank > RETRIEVAL_CANDIDATE_BREADTH:
                    verdict = f"cut by BREADTH (fused rank {rank} > {RETRIEVAL_CANDIDATE_BREADTH})"
                else:
                    verdict = f"cut by CONTEXT SLICE (fused rank {rank} > {FINAL_CONTEXT_SIZE})"
                print(f"    {cid:<24} {verdict}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
