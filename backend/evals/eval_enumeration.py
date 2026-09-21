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

    python -m evals.eval_enumeration                   # full: context + generation
    python -m evals.eval_enumeration --retrieval-only  # context columns only

--retrieval-only skips generate_grounded_answer entirely: no LLM call, no
throwaway app_user/chat_session rows, no message/citation rows. Only the
context_recall / ctx_contamination columns are produced (used_* show "-").
Because the model cannot cite what it was not given, used_contamination is
bounded above by ctx_contamination, so a zero here is a real guarantee.
"""

import argparse
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
from app.retrieval.actor import (
    ACTOR_MISMATCH_FACTOR,
    apply_actor_prior,
    detect_query_actor,
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
    # Same advisory prior production applies, over the same full list.
    fused = apply_actor_prior(
        fused, detect_query_actor(question), ACTOR_MISMATCH_FACTOR
    )
    return [f.result.citation_id for f in fused[:FINAL_CONTEXT_SIZE]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Enumeration-tier eval.")
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Context columns only: no generation, no LLM, no DB writes.",
    )
    args = parser.parse_args()

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

        chat = None
        if not args.retrieval_only:
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
            f"min_similarity={MIN_SIMILARITY}  "
            f"actor_mismatch_factor={ACTOR_MISMATCH_FACTOR}"
        )
        print(f"probe depth (diagnostic only): {PROBE_DEPTH}")
        if args.retrieval_only:
            print("mode: RETRIEVAL ONLY (no generation, no LLM, no DB writes)")
        print()

        rows = []
        details = []
        for e in entries:
            gold = list(e.get("gold") or [])
            forbidden = set(e.get("forbidden") or [])
            question = e["question"]

            ctx = context_slice(session, question, latest.id)
            in_ctx = [g for g in gold if g in ctx]
            ctx_contamination = [f for f in forbidden if f in ctx]

            if args.retrieval_only:
                cited, in_cited, contamination, abstained = None, None, None, None
            else:
                result = generate_grounded_answer(
                    session, question, latest.id, chat.id, write_trace=False
                )
                cited = [c.citation_id for c in result.citations]
                in_cited = [g for g in gold if g in cited]
                contamination = [f for f in forbidden if f in cited]
                abstained = result.answer.startswith("I don't have enough")

            rows.append(
                {
                    "id": e["id"],
                    "actor": e.get("actor", ""),
                    "query_actor": detect_query_actor(question) or "-",
                    "n_gold": len(gold),
                    "context_recall": len(in_ctx) / len(gold) if gold else 0.0,
                    "ctx_contamination": len(ctx_contamination),
                    "used_recall": (
                        len(in_cited) / len(gold)
                        if (gold and in_cited is not None)
                        else None
                    ),
                    "contamination": (
                        len(contamination) if contamination is not None else None
                    ),
                    "abstained": abstained,
                }
            )

            missing = [g for g in gold if g not in ctx]
            ranks = fused_ranks(session, question, latest.id) if missing else {}
            details.append(
                {
                    "id": e["id"],
                    "question": question,
                    "cited": cited,
                    "contamination": contamination or [],
                    "ctx_contamination": ctx_contamination,
                    "missing": [(g, ranks.get(g)) for g in missing],
                }
            )

        def fmt(v, width, spec=".3f"):
            return f"{'-':<{width}}" if v is None else f"{v:<{width}{spec}}"

        print("=" * 118)
        print(
            f"{'id':<28}{'actor':<10}{'q_actor':<10}{'gold':<6}{'ctx_recall':<12}"
            f"{'ctx_contam':<12}{'used_recall':<13}{'used_contam':<13}abstained"
        )
        print("=" * 118)
        for r in rows:
            print(
                f"{r['id']:<28}{r['actor']:<10}{r['query_actor']:<10}{r['n_gold']:<6}"
                f"{r['context_recall']:<12.3f}{r['ctx_contamination']:<12}"
                f"{fmt(r['used_recall'], 13)}{fmt(r['contamination'], 13, '')}"
                f"{'-' if r['abstained'] is None else r['abstained']}"
            )
        n = len(rows)
        used = [r["used_recall"] for r in rows if r["used_recall"] is not None]
        used_contam = [
            r["contamination"] for r in rows if r["contamination"] is not None
        ]
        print("-" * 118)
        print(
            f"{'MEAN / TOTAL':<28}{'':<10}{'':<10}{'':<6}"
            f"{sum(r['context_recall'] for r in rows) / n:<12.3f}"
            f"{sum(r['ctx_contamination'] for r in rows):<12}"
            f"{fmt(sum(used) / len(used) if used else None, 13)}"
            f"{fmt(sum(used_contam) if used_contam else None, 13, '')}"
        )

        print("\n" + "=" * 118)
        print("PER-QUERY DETAIL")
        print("=" * 118)
        for d in details:
            print(f"\n{d['id']}")
            print(f"  question: {d['question']}")
            if d["cited"] is not None:
                print(f"  cited   : {d['cited'] or '(none)'}")
            if d["ctx_contamination"]:
                print(f"  CTX CONTAMINATION : {d['ctx_contamination']}")
            if d["contamination"]:
                print(f"  USED CONTAMINATION: {d['contamination']}")
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
