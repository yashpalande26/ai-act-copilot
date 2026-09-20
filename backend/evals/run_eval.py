import argparse
import json
import math
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import AppUser, ChatSession, CorpusVersion
from app.db.session import SessionLocal
from app.generation.answer import (
    ABSTENTION_TEXT,
    GroundedAnswer,
    generate_grounded_answer,
)
from app.retrieval.search import (
    keyword_search,
    rrf_rank_and_fuse,
    vector_search,
)
from evals.judge import (
    judge_answer_relevance,
    judge_faithfulness,
    mean_score,
    pass_at_4_rate,
)

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.yaml"
GOLDEN_SET_HARD_PATH = Path(__file__).resolve().parent / "golden_set_hard.yaml"

# Retrieval depth. Recall@5/MRR slice [:RANK_CUTOFF] from this; nDCG uses the
# full depth. Fetching 10 and slicing is equivalent to fetching 5 - vector
# search is ORDER BY distance LIMIT n, and rrf_rank_and_fuse sorts the whole
# candidate union before slicing top_k - so the top 5 is unchanged either way.
RETRIEVAL_DEPTH = 10
RANK_CUTOFF = 5


def recall_at_k(retrieved_ids: list[str], expected_id: str) -> float:
    return 1.0 if expected_id in retrieved_ids else 0.0


def reciprocal_rank(retrieved_ids: list[str], expected_id: str) -> float:
    for i, cid in enumerate(retrieved_ids, start=1):
        if cid == expected_id:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], expected_id: str, k: int = 10) -> float:
    """nDCG@k with exactly one relevant document per query.

    IDCG is then 1 (the ideal ranking puts gold first), so this collapses to
    1/log2(rank+1) - the same rank information MRR uses under a gentler
    discount, NOT an independent third signal. Its value here is depth:
    Recall/MRR are measured at 5, this at 10, so it distinguishes "gold at
    rank 8" (partial credit) from "gold absent entirely" (zero).
    """
    for i, cid in enumerate(retrieved_ids[:k], start=1):
        if cid == expected_id:
            return 1.0 / math.log2(i + 1)
    return 0.0


def abstention_correct(answer: str, citations: list, expected_abstention: bool) -> bool:
    if expected_abstention:
        return answer == ABSTENTION_TEXT and len(citations) == 0
    return answer != ABSTENTION_TEXT


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[dict]:
    return json.loads(path.read_text())


def _run_retrieval(
    session, question: str, corpus_version_id: int, config: str
) -> list[str]:
    if config == "vector_only":
        results = vector_search(
            session,
            question,
            corpus_version_id,
            top_k=RETRIEVAL_DEPTH,
            min_similarity=0.0,
        )
        return [r.citation_id for r in results]

    vector_results = vector_search(
        session,
        question,
        corpus_version_id,
        top_k=RETRIEVAL_DEPTH,
        min_similarity=0.0,
    )
    lexical_results = keyword_search(
        session, question, corpus_version_id, top_k=RETRIEVAL_DEPTH
    )
    fused = rrf_rank_and_fuse(vector_results, lexical_results, top_k=RETRIEVAL_DEPTH)
    return [f.result.citation_id for f in fused]


def run_retrieval_eval(session, golden_set: list[dict], corpus_version_id: int):
    answerable = [g for g in golden_set if not g["expected_abstention"]]
    results: dict[str, list[tuple[float, float, float]]] = {
        "vector_only": [],
        "hybrid": [],
    }
    by_category: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
    detail = []

    for config in ("vector_only", "hybrid"):
        for item in answerable:
            retrieved_ids = _run_retrieval(
                session, item["question"], corpus_version_id, config
            )
            expected = item["expected_citation_id"]
            # Recall@5/MRR judge the top 5; nDCG looks the full depth.
            recall = recall_at_k(retrieved_ids[:RANK_CUTOFF], expected)
            rr = reciprocal_rank(retrieved_ids[:RANK_CUTOFF], expected)
            ndcg = ndcg_at_k(retrieved_ids, expected, k=RETRIEVAL_DEPTH)
            results[config].append((recall, rr, ndcg))
            by_category.setdefault(
                (item.get("category", "uncategorised"), config), []
            ).append((recall, rr, ndcg))
            rank = next(
                (i + 1 for i, cid in enumerate(retrieved_ids) if cid == expected),
                None,
            )
            detail.append((config, item["id"], recall == 1.0, rank, expected))

    return results, by_category, detail


def _mean_metrics(rows: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    if not rows:
        return 0.0, 0.0, 0.0
    n = len(rows)
    return (
        sum(r for r, _, _ in rows) / n,
        sum(rr for _, rr, _ in rows) / n,
        sum(nd for _, _, nd in rows) / n,
    )


def run_generation_eval(
    session, golden_set: list[dict], corpus_version_id: int, chat_session_id
):
    hit_results = []
    abstention_results = []
    detail = []
    judgeable: list[tuple[dict, GroundedAnswer]] = []

    for item in golden_set:
        result = generate_grounded_answer(
            session,
            item["question"],
            corpus_version_id,
            chat_session_id,
            write_trace=False,
        )
        correct_abstention = abstention_correct(
            result.answer, result.citations, item["expected_abstention"]
        )
        abstention_results.append(correct_abstention)

        if not item["expected_abstention"]:
            citation_ids = {c.citation_id for c in result.citations}
            hit = item["expected_citation_id"] in citation_ids
            hit_results.append(hit)
            status = "PASS" if hit and correct_abstention else "FAIL"
            detail.append((item["id"], status, hit, citation_ids))
            # Wave 2 (LLM-as-judge) only makes sense for a real, non-refused
            # answer - skip anything the model itself abstained on, even if
            # the golden set expected an answer.
            if result.answer != ABSTENTION_TEXT:
                judgeable.append((item, result))
        else:
            status = "PASS" if correct_abstention else "FAIL"
            detail.append((item["id"], status, None, None))

    return hit_results, abstention_results, detail, judgeable


def run_judge_eval(judgeable: list[tuple[dict, GroundedAnswer]]):
    faithfulness_results = []
    relevance_results = []
    detail = []

    for item, result in judgeable:
        context_chunks = [c.chunk_text for c in result.citations]
        faithfulness = judge_faithfulness(result.answer, context_chunks)
        relevance = judge_answer_relevance(item["question"], result.answer)
        faithfulness_results.append(faithfulness)
        relevance_results.append(relevance)
        detail.append((item["id"], faithfulness, relevance))

    return faithfulness_results, relevance_results, detail


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AI Act Copilot eval harness.")
    parser.add_argument(
        "--hard",
        action="store_true",
        help="Load golden_set_hard.yaml instead of golden_set.yaml.",
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Skip the generation and LLM-judge passes; retrieval metrics only.",
    )
    args = parser.parse_args()

    golden_set = load_golden_set(GOLDEN_SET_HARD_PATH if args.hard else GOLDEN_SET_PATH)

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

        ret_results, ret_by_category, ret_detail = run_retrieval_eval(
            session, golden_set, latest.id
        )

        print("=== Retrieval: vector_only vs hybrid (Recall@5 / MRR / nDCG@10) ===")
        print(f"{'config':<14}{'recall@5':<11}{'mrr':<9}ndcg@10")
        for config in ("vector_only", "hybrid"):
            mean_recall, mean_rr, mean_ndcg = _mean_metrics(ret_results[config])
            print(f"{config:<14}{mean_recall:<11.3f}{mean_rr:<9.3f}{mean_ndcg:.3f}")

        # Only meaningful when the loaded set is categorised - golden_set.yaml
        # has no category field, so the default run prints just the table above.
        categories = sorted(
            {c for c, _ in ret_by_category if c != "uncategorised"},
        )
        if categories:
            print("\n=== Retrieval by category (Recall@5 / MRR / nDCG@10) ===")
            print(
                f"{'category':<16}{'n':<5}{'config':<14}"
                f"{'recall@5':<11}{'mrr':<9}ndcg@10"
            )
            for category in categories:
                for config in ("vector_only", "hybrid"):
                    rows = ret_by_category.get((category, config), [])
                    mean_recall, mean_rr, mean_ndcg = _mean_metrics(rows)
                    print(
                        f"{category:<16}{len(rows):<5}{config:<14}"
                        f"{mean_recall:<11.3f}{mean_rr:<9.3f}{mean_ndcg:.3f}"
                    )

        print("\n--- per-question retrieval detail ---")
        for config, gid, passed, rank, expected in ret_detail:
            rank_str = str(rank) if rank else "-"
            status = "PASS" if passed else "FAIL"
            print(f"[{config}] {gid}  {status}  rank={rank_str}  expected={expected}")

        if args.retrieval_only:
            return

        # Generation needs a real chat_session_id - real FK chain, throwaway rows.
        user = AppUser(email=f"eval-run-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        chat_session = ChatSession(user_id=user.id, corpus_version_id=latest.id)
        session.add(chat_session)
        session.flush()
        session.commit()

        hit_results, abstention_results, gen_detail, judgeable = run_generation_eval(
            session, golden_set, latest.id, chat_session.id
        )

        print("\n=== Generation ===")
        hit_rate = sum(hit_results) / len(hit_results) if hit_results else 0.0
        abstention_accuracy = (
            sum(abstention_results) / len(abstention_results)
            if abstention_results
            else 0.0
        )
        print(
            f"citation_hit_rate:   {hit_rate:.3f}  ({sum(hit_results)}/{len(hit_results)} answerable)"
        )
        print(
            f"abstention_accuracy: {abstention_accuracy:.3f}  "
            f"({sum(abstention_results)}/{len(abstention_results)})"
        )

        print("\n--- per-question generation detail ---")
        for gid, status, hit, citation_ids in gen_detail:
            if hit is None:
                print(f"{gid}  {status}  abstention check")
            else:
                print(
                    f"{gid}  {status}  citation_hit={hit}  got={sorted(citation_ids)}"
                )

        faithfulness_results, relevance_results, judge_detail = run_judge_eval(
            judgeable
        )

        print("\n=== Wave 2: LLM-as-judge (faithfulness + answer-relevance) ===")
        n_judged = len(faithfulness_results)
        faithfulness_failures = sum(1 for r in faithfulness_results if r.score == 0)
        relevance_failures = sum(1 for r in relevance_results if r.score == 0)
        print(
            f"mean_faithfulness:      {mean_score(faithfulness_results):.3f}  "
            f"(parse failures: {faithfulness_failures}/{n_judged})"
        )
        print(
            f"mean_answer_relevance:  {mean_score(relevance_results):.3f}  "
            f"(parse failures: {relevance_failures}/{n_judged})"
        )
        print(f"faithfulness_pass@4:    {pass_at_4_rate(faithfulness_results):.3f}")
        print(f"relevance_pass@4:       {pass_at_4_rate(relevance_results):.3f}")

        print("\n--- per-question judge detail ---")
        for gid, faithfulness, relevance in judge_detail:
            print(
                f'{gid}  faithfulness={faithfulness.score}  "{faithfulness.rationale}"'
            )
            print(f'{gid}  relevance={relevance.score}  "{relevance.rationale}"')

        judged_ids = {item["id"] for item, _ in judgeable}
        skipped_ids = [
            item["id"] for item in golden_set if item["id"] not in judged_ids
        ]
        if skipped_ids:
            print(
                f"\n(skipped: {', '.join(skipped_ids)} - off-topic/abstained, "
                "faithfulness/relevance don't apply to a fixed refusal)"
            )
    finally:
        session.close()


if __name__ == "__main__":
    main()
