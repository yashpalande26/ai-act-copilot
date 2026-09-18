import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import AppUser, ChatSession, CorpusVersion
from app.db.session import SessionLocal
from app.generation.answer import (
    ABSTENTION_TEXT,
    generate_grounded_answer,
)
from app.retrieval.search import (
    keyword_search,
    rrf_rank_and_fuse,
    vector_search,
)

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.yaml"


def recall_at_k(retrieved_ids: list[str], expected_id: str) -> float:
    return 1.0 if expected_id in retrieved_ids else 0.0


def reciprocal_rank(retrieved_ids: list[str], expected_id: str) -> float:
    for i, cid in enumerate(retrieved_ids, start=1):
        if cid == expected_id:
            return 1.0 / i
    return 0.0


def abstention_correct(answer: str, citations: list, expected_abstention: bool) -> bool:
    if expected_abstention:
        return answer == ABSTENTION_TEXT and len(citations) == 0
    return answer != ABSTENTION_TEXT


def load_golden_set() -> list[dict]:
    return json.loads(GOLDEN_SET_PATH.read_text())


def _run_retrieval(
    session, question: str, corpus_version_id: int, config: str
) -> list[str]:
    if config == "vector_only":
        results = vector_search(
            session, question, corpus_version_id, top_k=5, min_similarity=0.0
        )
        return [r.citation_id for r in results]

    vector_results = vector_search(
        session, question, corpus_version_id, top_k=10, min_similarity=0.0
    )
    lexical_results = keyword_search(session, question, corpus_version_id, top_k=10)
    fused = rrf_rank_and_fuse(vector_results, lexical_results, top_k=5)
    return [f.result.citation_id for f in fused]


def run_retrieval_eval(session, golden_set: list[dict], corpus_version_id: int):
    answerable = [g for g in golden_set if not g["expected_abstention"]]
    results: dict[str, list[tuple[float, float]]] = {"vector_only": [], "hybrid": []}
    detail = []

    for config in ("vector_only", "hybrid"):
        for item in answerable:
            retrieved_ids = _run_retrieval(
                session, item["question"], corpus_version_id, config
            )
            recall = recall_at_k(retrieved_ids, item["expected_citation_id"])
            rr = reciprocal_rank(retrieved_ids, item["expected_citation_id"])
            results[config].append((recall, rr))
            rank = next(
                (
                    i + 1
                    for i, cid in enumerate(retrieved_ids)
                    if cid == item["expected_citation_id"]
                ),
                None,
            )
            detail.append(
                (config, item["id"], recall == 1.0, rank, item["expected_citation_id"])
            )

    return results, detail


def run_generation_eval(
    session, golden_set: list[dict], corpus_version_id: int, chat_session_id
):
    hit_results = []
    abstention_results = []
    detail = []

    for item in golden_set:
        result = generate_grounded_answer(
            session, item["question"], corpus_version_id, chat_session_id
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
        else:
            status = "PASS" if correct_abstention else "FAIL"
            detail.append((item["id"], status, None, None))

    return hit_results, abstention_results, detail


def main() -> None:
    golden_set = load_golden_set()

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

        ret_results, ret_detail = run_retrieval_eval(session, golden_set, latest.id)

        print("=== Retrieval: vector_only vs hybrid (Recall@5 / MRR) ===")
        print(f"{'config':<14}{'recall@5':<11}mrr")
        for config in ("vector_only", "hybrid"):
            recalls = [r for r, _ in ret_results[config]]
            rrs = [rr for _, rr in ret_results[config]]
            mean_recall = sum(recalls) / len(recalls) if recalls else 0.0
            mean_rr = sum(rrs) / len(rrs) if rrs else 0.0
            print(f"{config:<14}{mean_recall:<11.3f}{mean_rr:.3f}")

        print("\n--- per-question retrieval detail ---")
        for config, gid, passed, rank, expected in ret_detail:
            rank_str = str(rank) if rank else "-"
            status = "PASS" if passed else "FAIL"
            print(f"[{config}] {gid}  {status}  rank={rank_str}  expected={expected}")

        # Generation needs a real chat_session_id - real FK chain, throwaway rows.
        user = AppUser(email=f"eval-run-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        chat_session = ChatSession(user_id=user.id, corpus_version_id=latest.id)
        session.add(chat_session)
        session.flush()
        session.commit()

        hit_results, abstention_results, gen_detail = run_generation_eval(
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
    finally:
        session.close()


if __name__ == "__main__":
    main()
