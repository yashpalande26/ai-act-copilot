"""The agentic-RAG eval harness: per-trace metrics over the four-bucket set,
through the SAME entry point /ask uses (generate_grounded_answer), so the
AGENTIC_RAG flag applies to the run exactly as it would to a user.

    python evals/run_agentic_eval.py --json out/off.json
    AGENTIC_RAG=1 python evals/run_agentic_eval.py --json out/on.json
    python evals/gate.py out/off.json out/on.json --equivalence

Per trace (evals/metrics.py): context_recall, context_precision (against the
15-chunk context the pipeline ACTUALLY served, captured from retrieve_step,
so a rewrite node's effect on the context is measured, not the raw question's
retrieval), citation_accuracy (gold covered by the returned citations),
inline_mention, predicted_abstention, and with the judge on (default)
faithfulness and answer_relevance from evals/judge.py. Aggregated per bucket
and pooled, with abstention F1_ans / F1_ref / macro.

Stage 1 fields per trace: rewrite_outcome (applied | guarded | ambiguous |
None), rewritten_query, rewrite_introduced (the entities the guard rejected),
served_introduced: an INDEPENDENT re-check of every served rewrite against
the conversation (must be empty; the guard is tested, not trusted).

Multi-turn items seed their history as Message rows in a fresh chat session
before the follow-up is asked, so a Stage 1 rewrite node can read it through
load_history. Nothing persists: the session's commit is pointed at flush and
the run ends with a rollback.

Paid: one gpt-4o call per item (~35), two query embeddings per item, and two
gpt-4o-mini judge calls per answered item. Roughly $0.25 per run.

VALIDITY: single-hop, multi-turn and unanswerable items are reused from the
existing sets (each item names its source); the multi-hop items were authored
on 22 Sep 2026 by the same person who wrote the prompt and are marked for
review. The set cannot see real user phrasing. gpt-4o at temperature 0 is not
deterministic: compare judged numbers across runs with that in mind; the
deterministic fields are what evals/gate.py --equivalence asserts.
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config import (
    agentic_grade_enabled,
    agentic_rag_enabled,
    agentic_rewrite_enabled,
)
from app.db.models import AppUser, ChatSession, CorpusVersion, Message
from app.db.session import SessionLocal
from app.generation import answer as answer_module
from app.generation import graph as graph_module
from app.generation.answer import generate_grounded_answer, is_abstention
from app.generation.rewrite import _transcript, introduced_entities
from evals.judge import judge_answer_relevance, judge_faithfulness
from evals.metrics import (
    abstention_f1,
    citation_accuracy,
    context_precision,
    context_recall,
    inline_mention,
    mean,
)

HERE = Path(__file__).resolve().parent
SET_PATH = HERE / "agentic_set.json"
CONTEXT = 15
BUCKETS = ("single_hop", "multi_turn", "multi_hop", "unanswerable")


def summarise(traces: list[dict]) -> dict:
    answerable = [t for t in traces if not t["expected_abstention"]]
    judged = [t for t in traces if t.get("faithfulness")]
    f1 = abstention_f1(
        [(t["expected_abstention"], t["predicted_abstention"]) for t in traces]
    )
    return {
        "n": len(traces),
        "context_recall": mean([t["context_recall"] for t in answerable]),
        "context_precision": mean([t["context_precision"] for t in answerable]),
        "citation_accuracy": mean([t["citation_accuracy"] for t in answerable]),
        "inline_mention": mean(
            [
                float(t["inline_mention"])
                for t in answerable
                if t["inline_mention"] is not None and not t["predicted_abstention"]
            ]
        ),
        "faithfulness": mean([t["faithfulness"] / 5 for t in judged]),
        "faithfulness_pass_at_4": mean([float(t["faithfulness"] >= 4) for t in judged]),
        "answer_relevance": mean([t["answer_relevance"] / 5 for t in judged]),
        "abstention_f1": f1.macro,
        "f1_ans": f1.f1_ans,
        "f1_ref": f1.f1_ref,
        "answered": sum(not t["predicted_abstention"] for t in traces),
        "judged": len(judged),
    }


def fmt(v) -> str:
    return "  n/a" if v is None else f"{v:.3f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", type=Path, default=SET_PATH)
    ap.add_argument("--only", help="comma-separated ids")
    ap.add_argument("--bucket", choices=BUCKETS)
    ap.add_argument("--no-judge", action="store_true", help="skip the paid judge calls")
    ap.add_argument("--json", type=Path, help="write per-trace rows and summaries here")
    args = ap.parse_args()

    items = json.loads(args.set.read_text())
    if args.only:
        only = set(args.only.split(","))
        items = [i for i in items if i["id"] in only]
    if args.bucket:
        items = [i for i in items if i["bucket"] == args.bucket]

    flag = agentic_rag_enabled()
    node = agentic_rewrite_enabled()
    grader = agentic_grade_enabled()
    # Capture what the pipeline served: the context slice that reached decide
    # (after any grading), the rewrite, the grade outcomes and how many times
    # retrieval ran (the bounded widen allows at most two).
    captured: dict = {}
    real_retrieve = answer_module.retrieve_step
    real_decide = answer_module.decide_step
    real_rewrite = graph_module.rewrite_followup
    real_grade = graph_module.grade_context

    def capturing_retrieve(sess, query, cv_id, **kw):
        step = real_retrieve(sess, query, cv_id, **kw)
        captured.setdefault("retrieve_calls", 0)
        captured["retrieve_calls"] += 1
        captured["retrieval_query"] = query
        return step

    def capturing_decide(
        sess, query, stored, cv_id, chat_id, retrieved, generated, **kw
    ):
        captured["retrieved"] = retrieved
        captured["path_tag"] = kw.get("path_tag", "")
        return real_decide(
            sess, query, stored, cv_id, chat_id, retrieved, generated, **kw
        )

    def capturing_grade(query, fused, extractor=None):
        res = real_grade(query, fused, extractor)
        captured.setdefault("grades", []).append(res)
        return res

    def capturing_rewrite(history, question, extractor=None):
        res = real_rewrite(history, question, extractor)
        captured["rewrite"] = res
        captured["history"] = history
        return res

    answer_module.retrieve_step = capturing_retrieve
    answer_module.decide_step = capturing_decide
    graph_module.rewrite_followup = capturing_rewrite
    graph_module.grade_context = capturing_grade
    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush  # nothing persists
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        user = AppUser(email=f"agentic-eval-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        print(
            f"set {args.set.name} ({len(items)} items)  corpus {cv.consolidated_date}"
            f"  AGENTIC_RAG={'1' if flag else '0'}  AGENTIC_REWRITE={'1' if node else '0'}"
            f"  AGENTIC_GRADE={'1' if grader else '0'}"
            f"  judge={'off' if args.no_judge else 'on'}"
            f"  env {os.environ.get('APP_ENV', 'dev')}"
        )
        traces: list[dict] = []
        for it in items:
            chat = ChatSession(user_id=user.id, corpus_version_id=cv.id, title="eval")
            session.add(chat)
            session.flush()
            for role, content in it.get("history", []):
                session.add(Message(session_id=chat.id, role=role, content=content))
            session.flush()
            q = it["question"]
            gold = it["gold_citation_ids"]
            captured.clear()
            t0 = time.monotonic()
            res = generate_grounded_answer(
                session, q, cv.id, chat.id, max_output_tokens=800
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            abstained = is_abstention(res.answer)
            cited = [c.citation_id for c in res.citations]
            step = captured.get("retrieved")
            context_ids = [f.result.citation_id for f in step.fused] if step else []
            cfg = (step.retrieval_config if step else "none") + captured.get(
                "path_tag", ""
            )
            grades = captured.get("grades", [])
            tag = captured.get("path_tag", "")
            grade_outcome = next(
                (
                    k
                    for k in ("proceed", "widened", "abstain", "skipped")
                    if f"grade={k}" in tag
                ),
                None,
            )
            rw = captured.get("rewrite")
            served_rewrite = (
                rw.query
                if rw is not None
                and rw.applied
                and captured.get("retrieval_query") == rw.query
                else None
            )
            served_introduced = (
                introduced_entities(
                    served_rewrite, _transcript(captured["history"]) + "\n" + q
                )
                if served_rewrite
                else []
            )
            outcome = None
            if rw is not None and rw.attempted:
                if served_rewrite:
                    outcome = "applied"
                elif rw.introduced:
                    outcome = "guarded"
                elif rw.applied:
                    outcome = "ambiguous"
                else:
                    outcome = "passthrough"
            row = {
                "id": it["id"],
                "bucket": it["bucket"],
                "source": it["source"],
                "question": q,
                "gold_citation_ids": gold,
                "expected_abstention": it["expected_abstention"],
                "predicted_abstention": abstained,
                "context_ids": context_ids,
                "retrieval_config": cfg,
                "rewrite_outcome": outcome,
                "grade_outcome": grade_outcome,
                "grade_relevant_counts": [len(g.relevant) for g in grades],
                "grade_tokens": sum(
                    (g.prompt_tokens or 0) + (g.completion_tokens or 0) for g in grades
                ),
                "retrieve_calls": captured.get("retrieve_calls", 0),
                "rewritten_query": served_rewrite,
                "rewrite_introduced": list(rw.introduced) if rw is not None else [],
                "served_introduced": served_introduced,
                "context_recall": context_recall(context_ids, gold),
                "context_precision": context_precision(context_ids, gold),
                "citation_accuracy": citation_accuracy(cited, gold),
                "inline_mention": None
                if abstained
                else inline_mention(res.answer, gold),
                "latency_ms": latency_ms,
                "answer": res.answer[:300],
            }
            if not args.no_judge and not abstained:
                f = judge_faithfulness(
                    res.answer,
                    [c.chunk_text for c in res.citations],
                    [c.citation_label for c in res.citations],
                )
                r = judge_answer_relevance(q, res.answer)
                row["faithfulness"] = f.score or None
                row["faithfulness_rationale"] = f.rationale
                row["answer_relevance"] = r.score or None
            traces.append(row)
            print(
                f"  {it['id']} {it['bucket']:<12} abstain={'Y' if abstained else 'n'}"
                f"{'(exp)' if it['expected_abstention'] else '     '}"
                f" ctx_recall={fmt(row['context_recall'])} ctx_prec={fmt(row['context_precision'])}"
                f" cite={fmt(row['citation_accuracy'])} inline={row['inline_mention']}"
                f" faith={row.get('faithfulness')} rel={row.get('answer_relevance')}"
                f" {latency_ms}ms | {q[:70]}"
                + (
                    f" grade={grade_outcome} rel={[len(g.relevant) for g in grades]} retrieves={captured.get('retrieve_calls', 0)}"
                    if grade_outcome
                    else ""
                )
                + (
                    f"\n      rewrite[{outcome}]: {served_rewrite or rw.query if rw else ''}"
                    + (
                        f" REJECTED {list(rw.introduced)}"
                        if rw is not None and rw.introduced
                        else ""
                    )
                    if outcome
                    else ""
                )
            )

        by_bucket = defaultdict(list)
        for t in traces:
            by_bucket[t["bucket"]].append(t)
        buckets = {b: summarise(rows) for b, rows in by_bucket.items()}
        pooled = summarise(traces)
        cols = (
            "n",
            "context_recall",
            "context_precision",
            "citation_accuracy",
            "inline_mention",
            "faithfulness",
            "faithfulness_pass_at_4",
            "answer_relevance",
            "f1_ans",
            "f1_ref",
            "abstention_f1",
            "answered",
            "judged",
        )
        print("\n== SUMMARY (per bucket, then pooled; judged scores scaled to 0-1) ==")
        print(f"{'bucket':<14}" + "".join(f"{c[:11]:>12}" for c in cols))
        for b in BUCKETS:
            if b in buckets:
                s = buckets[b]
                print(
                    f"{b:<14}"
                    + "".join(
                        f"{(s[c] if isinstance(s[c], int) else fmt(s[c])):>12}"
                        for c in cols
                    )
                )
        print(
            f"{'POOLED':<14}"
            + "".join(
                f"{(pooled[c] if isinstance(pooled[c], int) else fmt(pooled[c])):>12}"
                for c in cols
            )
        )
        print(
            "abstention F1 is macro(F1_ans, F1_ref); n/a means the class had no expected and no predicted members."
        )
        graded = [t for t in traces if t["grade_outcome"]]
        if graded:
            counts = {
                k: sum(t["grade_outcome"] == k for t in graded)
                for k in ("proceed", "widened", "abstain", "skipped")
            }
            print(
                f"\n== GRADE NODE ==  graded {len(graded)}  "
                + "  ".join(f"{k} {v}" for k, v in counts.items())
                + f"  max retrieve calls per turn {max(t['retrieve_calls'] for t in traces)} (bound 2)"
                + f"  gpt-4o calls avoided by grader abstention {counts['abstain']}"
                + f"  grader tokens total {sum(t['grade_tokens'] for t in traces)}"
            )
            wrong = [
                t["id"]
                for t in graded
                if t["grade_outcome"] == "abstain" and not t["expected_abstention"]
            ]
            print(
                f"  answerable items the grader abstained on (must be 0): {len(wrong)} {wrong}"
            )
        attempted = [t for t in traces if t["rewrite_outcome"]]
        if attempted:
            outcomes = {
                k: sum(t["rewrite_outcome"] == k for t in attempted)
                for k in ("applied", "guarded", "ambiguous", "passthrough")
            }
            leaked = [t["id"] for t in traces if t["served_introduced"]]
            print(
                f"\n== REWRITE NODE ==  attempted {len(attempted)}  "
                + "  ".join(f"{k} {v}" for k, v in outcomes.items())
            )
            print(
                f"  drift-guard rejections (caught, fell back): {outcomes['guarded']}"
            )
            print(
                f"  served rewrites that introduce an entity absent from the conversation (independent re-check, gate 0): {len(leaked)} {leaked}"
            )
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(
                json.dumps(
                    {
                        "agentic_rag": flag,
                        "set": args.set.name,
                        "corpus": str(cv.consolidated_date),
                        "pooled": pooled,
                        "buckets": buckets,
                        "traces": traces,
                    },
                    indent=1,
                )
            )
            print(f"wrote {args.json}")
    finally:
        answer_module.retrieve_step = real_retrieve
        answer_module.decide_step = real_decide
        graph_module.rewrite_followup = real_rewrite
        graph_module.grade_context = real_grade
        session.commit = real_commit
        session.rollback()
        session.close()


if __name__ == "__main__":
    main()
