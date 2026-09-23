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
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app import config
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
from app.generation.understand import verdict_leaks
from app.generation.verify import (
    binding_references,
    is_recital,
    recital_only_citation,
    references_in,
)
from app.retrieval import recital_map
from evals import judge
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
SMOKE_PATH = HERE / "smoke_subset.json"
CONTEXT = 15
BUCKETS = (
    "single_hop",
    "multi_turn",
    "multi_hop",
    "unanswerable",
    "reference",
    "plain_language",
    "why",
)


def compare_to_baseline(path: Path, traces: list[dict], judge_model: str) -> None:
    """Item-by-item comparison against a SAVED run file (ADR-31): the
    deterministic fields must match on every shared item; the judged metrics
    are shown side by side and are only comparable when both runs used the
    same judge. Items missing from the baseline are listed, not compared."""
    base = json.loads(path.read_text())
    b = {t["id"]: t for t in base["traces"]}
    shared = [t for t in traces if t["id"] in b]
    missing = [t["id"] for t in traces if t["id"] not in b]
    fields = ("context_recall", "predicted_abstention", "citation_accuracy")
    diffs = [
        (t["id"], f, b[t["id"]][f], t[f])
        for t in shared
        for f in fields
        if b[t["id"]][f] != t[f]
    ]
    print(
        f"\n== BASELINE {path.name}: {len(shared)} shared items, "
        f"{len(missing)} not in baseline {missing}"
    )
    print(
        "  deterministic differences on shared items (recall, abstention, citations): "
        f"{len(diffs)}"
    )
    for d in diffs:
        print("   ", d)
    # Run files before ADR-31 carry no judge_model; they were all judged with gpt-4o-mini.
    base_judge = base.get("judge_model") or "gpt-4o-mini"
    print(
        f"  judge: baseline {base_judge}, this run {judge_model}"
        + (
            ""
            if base_judge == judge_model
            else "  (DIFFERENT: judged metrics not comparable)"
        )
    )

    def pooled_of(rows, k):
        vals = [r[k] for r in rows if r.get(k) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    brows = [b[t["id"]] for t in shared]
    for k in (
        "context_recall",
        "citation_accuracy",
        "faithfulness",
        "answer_relevance",
    ):
        print(
            f"  {k:<18} baseline {pooled_of(brows, k)}  this run {pooled_of(shared, k)}"
            "  (shared items)"
        )
    leaks = [t["id"] for t in traces if t["verdict_leaks"]]
    print(f"  verdict leaks this run (must be 0): {len(leaks)} {leaks}")


def summarise(traces: list[dict]) -> dict:
    # route-or-abstain items (ADR-21: a use the Act does not name) have no
    # gold and no expected class: an abstention and a provision-free routed
    # explanation are both correct, so they are outside recall and F1.
    scored = [t for t in traces if not t.get("route_or_abstain")]
    answerable = [t for t in scored if not t["expected_abstention"]]
    judged = [t for t in traces if t.get("faithfulness")]
    f1 = abstention_f1(
        [(t["expected_abstention"], t["predicted_abstention"]) for t in scored]
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
    # Cheap mode (ADR-31): iterate fast, gate on the full set.
    ap.add_argument(
        "--judge-model",
        default=judge.JUDGE_MODEL,
        help=(
            "judge model for faithfulness and relevance (default: the model the saved "
            "baselines were judged with, recorded in each run file). A different judge "
            "is a directional signal only, never a gate decision."
        ),
    )
    ap.add_argument(
        "--subset",
        choices=("smoke",),
        help="run only evals/smoke_subset.json (one or two items per bucket)",
    )
    ap.add_argument(
        "--baseline",
        type=Path,
        help="a saved run file to compare against, item by item, instead of rerunning flag-off",
    )
    ap.add_argument(
        "--cheap",
        action="store_true",
        help=(
            "preset: --subset smoke, --judge-model gpt-4o-mini, and VERIFY_MODEL=openai:gpt-4o-mini "
            "unless VERIFY_MODEL is already set. Directional only."
        ),
    )
    args = ap.parse_args()
    if args.cheap:
        # --only names the items itself; forcing the smoke subset on top of it
        # intersected the two and silently ran nothing (23 Sep 2026).
        args.subset = args.subset or (None if args.only else "smoke")
        args.judge_model = "gpt-4o-mini"
        os.environ.setdefault("VERIFY_MODEL", "openai:gpt-4o-mini")
    judge.JUDGE_MODEL = args.judge_model

    items = json.loads(args.set.read_text())
    if args.subset:
        smoke = set(json.loads(SMOKE_PATH.read_text())["agentic"])
        items = [i for i in items if i["id"] in smoke]
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
    real_verify = graph_module.verify_answer
    real_generate = answer_module.generate_step

    def capturing_verify(answer, fused, extractor=None):
        res = real_verify(answer, fused, extractor)
        captured.setdefault("verifies", []).append(res)
        return res

    def capturing_generate(query, fused, **kw):
        captured["generate_calls"] = captured.get("generate_calls", 0) + 1
        return real_generate(query, fused, **kw)

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
    graph_module.verify_answer = capturing_verify
    answer_module.generate_step = capturing_generate
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
        edges_by_recital: dict[str, list] = {}
        for e in recital_map.load_edges(session, cv.id):
            edges_by_recital.setdefault(e.recital, []).append(e)
        print(
            f"set {args.set.name} ({len(items)} items)  corpus {cv.consolidated_date}"
            f"  AGENTIC_RAG={'1' if flag else '0'}  AGENTIC_REWRITE={'1' if node else '0'}"
            f"  AGENTIC_GRADE={'1' if grader else '0'}"
            f"  judge={'off' if args.no_judge else args.judge_model}"
            f"  verifier={config.verify_model()}"
            f"  subset={args.subset or 'full'}"
            f"  env {os.environ.get('APP_ENV', 'dev')}"
        )
        if args.cheap or args.judge_model != "gpt-4o-mini" or args.subset:
            print(
                "  NOTE: cheap or non-default settings; treat the numbers as directional, "
                "not as a gate."
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
            # ADR-24: a clarifying question is neither an answer nor the
            # abstention; recorded on its own, never judged for faithfulness.
            clarifying = bool(getattr(res, "clarifying", False))
            cited = [c.citation_id for c in res.citations]
            step = captured.get("retrieved")
            # A clarifying turn serves no citations (fused is emptied by the
            # clarify node); the context that was retrieved and graded before
            # the question is the first slice of all_fused, which is what the
            # recall metric should see.
            context_ids = (
                [f.result.citation_id for f in step.all_fused[:15]]
                if step and clarifying
                else [f.result.citation_id for f in step.fused]
                if step
                else []
            )
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
            dm = re.search(r"decompose=(applied:(\d+)|skipped)", tag + cfg)
            decompose_outcome = (
                None if dm is None else ("applied" if dm.group(2) else "skipped")
            )
            sub_queries = int(dm.group(2)) if dm and dm.group(2) else 0
            verifies = captured.get("verifies", [])
            verify_outcome = next(
                (
                    k
                    for k in ("passed", "regenerated", "abstained", "skipped")
                    if f"verify={k}" in tag
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
                "decompose_outcome": decompose_outcome,
                "understand_outcome": (
                    "applied"
                    if "understand=applied" in cfg
                    else ("n/a" if "understand=n/a" in cfg else None)
                ),
                "system_description": bool(getattr(res, "system_description", False)),
                "clarifying": clarifying,
                "verdict_leaks": [] if abstained else verdict_leaks(res.answer),
                "leak_outcome": next(
                    (k for k in ("regenerated", "abstained") if f"leak={k}" in tag),
                    None,
                ),
                "must_route": it.get("must_route", False),
                "route_or_abstain": it.get("route_or_abstain", False),
                "names_provision": [] if abstained else references_in(res.answer),
                # ADR-32: recitals in the served context and in the answer
                "recitals_in_context": sum(is_recital(c) for c in context_ids),
                # ADR-33: a recital in the slice must have a linked provision in the slice
                "recitals_without_provision": [
                    c
                    for c in context_ids
                    if is_recital(c)
                    and not any(
                        recital_map._matches(e.target, o)
                        for e in edges_by_recital.get(c, [])
                        for o in context_ids
                        if not is_recital(o)
                    )
                ],
                "recital_at_rank0": bool(context_ids) and is_recital(context_ids[0]),
                "names_recital": []
                if abstained
                else [r for r in references_in(res.answer) if is_recital(r)],
                "recital_only": False
                if abstained or clarifying
                else recital_only_citation(res.answer),
                "operative_named": []
                if abstained
                else binding_references(references_in(res.answer)),
                "sub_queries": sub_queries,
                "verify_outcome": verify_outcome,
                "verify_unsupported": [list(v.unsupported_claims) for v in verifies],
                "verify_missing_refs": [list(v.missing_references) for v in verifies],
                "verify_tokens": sum(
                    (v.prompt_tokens or 0) + (v.completion_tokens or 0)
                    for v in verifies
                ),
                "generate_calls": captured.get("generate_calls", 0),
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
            if not args.no_judge and not abstained and not clarifying:
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
                f"{' CLARIFY' if clarifying else ''}"
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
                + f"  max retrieve calls per turn {max(t['retrieve_calls'] for t in traces)} (bound 2 per part)"
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
        decomposed = [t for t in traces if t["decompose_outcome"] == "applied"]
        planned = [t for t in traces if t["decompose_outcome"]]
        if planned:
            over = [
                t["id"]
                for t in decomposed
                if t["retrieve_calls"] > 2 * t["sub_queries"]
            ]
            print(
                f"\n== DECOMPOSE NODE ==  seen {len(planned)}  applied {len(decomposed)}  skipped {len(planned) - len(decomposed)}"
                f"  sub-queries per applied item {[t['sub_queries'] for t in decomposed]}"
                f"  items exceeding 2 retrievals per part (must be 0): {len(over)} {over}"
            )
            fired_outside = [t["id"] for t in decomposed if t["bucket"] != "multi_hop"]
            print(
                f"  applied outside multi_hop (must be 0): {len(fired_outside)} {fired_outside}"
            )
        recital_only = [t["id"] for t in traces if t["recital_only"]]
        orphan = [
            (t["id"], t["recitals_without_provision"])
            for t in traces
            if t["recitals_without_provision"]
        ]
        print(
            f"\n== RECITAL MAP (ADR-33) ==  RECITAL_MAP={'on' if config.recital_map_enabled() else 'off'}"
            f"  recital in context without its linked provision (must be 0 when on): {len(orphan)} {orphan[:6]}"
            f"  map edges loaded: {sum(len(v) for v in edges_by_recital.values())}"
        )
        direct = [t for t in traces if t["bucket"] not in ("why", "unanswerable")]
        rec0 = [t["id"] for t in direct if t["recital_at_rank0"]]
        print(
            f"\n== RECITALS (ADR-32) ==  recital cited as the only provision (must be 0): {len(recital_only)} {recital_only}"
            f"  recital at context rank 0 on a direct-provision item (must be 0): {len(rec0)} {rec0}"
            f"  mean recitals in the served context, direct items: {round(sum(t['recitals_in_context'] for t in direct) / max(len(direct), 1), 2)}"
        )
        why = [t for t in traces if t["bucket"] == "why"]
        if why:
            ok = [
                t["id"]
                for t in why
                if t["context_recall"] == 1.0
                and not t["predicted_abstention"]
                and t["names_recital"]
                and t["operative_named"]
            ]
            print(
                f"  why items: recital and operative provision both in context and both named: {len(ok)}/{len(why)} {ok}"
                + "".join(
                    f"\n    {t['id']}: recall={t['context_recall']} named={t['names_provision'][:4]} recitals_in_ctx={t['recitals_in_context']}"
                    for t in why
                )
            )
        leaks = [(t["id"], t["verdict_leaks"][0]) for t in traces if t["verdict_leaks"]]
        print(
            f"\n== VERDICT LEAKAGE (hard safety gate, must be 0 on every item) ==  {len(leaks)} {leaks}"
        )
        plain = [t for t in traces if t["bucket"] == "plain_language"]
        if plain:
            unnamed = [t for t in plain if t["route_or_abstain"]]
            unnamed_ok = [
                t["id"]
                for t in unnamed
                if (t["predicted_abstention"] or t["system_description"])
                and not t["names_provision"]
            ]
            stretched = [t["id"] for t in unnamed if t["names_provision"]]
            print(
                f"== UN-NAMED USES (route or abstain, no provision asserted) ==  ok {len(unnamed_ok)}/{len(unnamed)} {unnamed_ok}"
                f"  stretched to a provision (must be 0): {len(stretched)} {stretched}"
            )
            print(
                "== PLAIN LANGUAGE ==  understood "
                f"{sum(t['understand_outcome'] == 'applied' for t in plain)}/{len(plain)}"
                f"  routed {sum(t['system_description'] for t in plain if t['must_route'])}/{sum(t['must_route'] for t in plain)} of must-route"
                f"  off-topic item routed (must be 0): {sum(t['system_description'] for t in plain if t['expected_abstention'])}"
                f"  leak regenerations {sum(t['leak_outcome'] == 'regenerated' for t in traces)}  leak abstentions {sum(t['leak_outcome'] == 'abstained' for t in traces)}"
                f"  clarifying question asked {sum(t['clarifying'] for t in traces)} {[t['id'] for t in traces if t['clarifying']]}"
            )
        verified = [t for t in traces if t["verify_outcome"]]
        if verified:
            vc = {
                k: sum(t["verify_outcome"] == k for t in verified)
                for k in ("passed", "regenerated", "abstained", "skipped")
            }
            print(
                f"\n== VERIFY NODE ==  verified {len(verified)}  "
                + "  ".join(f"{k} {v}" for k, v in vc.items())
                + f"  max generate calls per turn {max(t['generate_calls'] for t in traces)} (bound 2)"
                + f"  verifier tokens total {sum(t['verify_tokens'] for t in traces)}"
            )
            flagged = [
                t["id"]
                for t in verified
                if t["verify_outcome"] in ("regenerated", "abstained")
            ]
            print(f"  answers flagged on first pass: {len(flagged)} {flagged}")
            for t in verified:
                if t["verify_outcome"] in ("regenerated", "abstained"):
                    print(
                        f"    {t['id']}: missing refs {t['verify_missing_refs'][0]}; unsupported {t['verify_unsupported'][0][:3]}"
                    )
            wrong = [
                t["id"]
                for t in verified
                if t["verify_outcome"] == "abstained" and not t["expected_abstention"]
            ]
            print(f"  answerable items the verifier abstained on: {len(wrong)} {wrong}")
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
                        "subset": args.subset,
                        "judge_model": None if args.no_judge else args.judge_model,
                        "verify_model": config.verify_model(),
                        "recital_map": config.recital_map_enabled(),
                        "corpus": str(cv.consolidated_date),
                        "pooled": pooled,
                        "buckets": buckets,
                        "traces": traces,
                    },
                    indent=1,
                )
            )
            print(f"wrote {args.json}")
        if args.baseline:
            compare_to_baseline(args.baseline, traces, args.judge_model)
    finally:
        answer_module.retrieve_step = real_retrieve
        answer_module.decide_step = real_decide
        graph_module.rewrite_followup = real_rewrite
        graph_module.grade_context = real_grade
        graph_module.verify_answer = real_verify
        answer_module.generate_step = real_generate
        session.commit = real_commit
        session.rollback()
        session.close()


if __name__ == "__main__":
    main()
