"""Risk-tier framing eval (ADR-27): single-turn system descriptions across the
Regulation's tiers, through generate_grounded_answer (the graph) with the
flags as set in the environment. Nothing persists.

    AGENTIC_RAG=1 CLARIFY_FOLLOWUP=0 RISK_TIER_FRAMING=0 python evals/run_risk_tier_eval.py --json off.json
    AGENTIC_RAG=1 CLARIFY_FOLLOWUP=0 RISK_TIER_FRAMING=1 python evals/run_risk_tier_eval.py --repeats 3 --json on.json

CLARIFY_FOLLOWUP is set to 0 for this eval on purpose: the thing under test is
the generator's own decision on the first turn (answer, honest not-listed
answer, or abstain and route), which the clarifying question would replace.

Buckets (evals/risk_tier_set.json): transparency (interactive or generative
systems; expect the transparency provision surfaced), not_listed (no listed
category; expect an honest answer that none of the retrieved provisions names
the use, with any general obligation, not a bare abstention), high_risk (must
still ground on the existing gold), law_silent (property valuation; must
abstain and route with zero provisions named), prohibited (social scoring;
expect the prohibited-practice provision surfaced).

Split gate. ABSOLUTE, summed over every draw, must be 0: verdict leaks; a
named provision under a forbidden prefix (a stretch to a tier or category
the item's gold does not sanction); a named provision not in the served
context; a high_risk item that does not ground on its gold; the law_silent
item answered or naming any provision. VALUE, per item by majority of draws:
transparency items answer naming a gold transparency provision; not_listed
items answer (not the abstention) with no stretch; the prohibited item names
its gold.

VALIDITY: 14 items authored by the person who wrote the prompts; they prove
the framing behaves on these kinds of description, not how often real
descriptions are framed correctly.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app import config
from app.db.models import AppUser, ChatSession, CorpusVersion
from app.db.session import SessionLocal
from app.generation import graph as graph_module
from app.generation.answer import generate_grounded_answer, is_abstention
from app.generation.understand import verdict_leaks
from app.generation.verify import missing_references, references_in
from evals.metrics import context_recall

HERE = Path(__file__).resolve().parent
HONEST = re.compile(
    r"none of the (?:retrieved )?provisions|not (?:among|listed|named|mentioned)",
    re.IGNORECASE,
)


def _covers(named: str, gold: str) -> bool:
    return named == gold or gold.startswith(named + ".") or named.startswith(gold + ".")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--only", help="comma-separated item ids")
    ap.add_argument("--json", type=Path)
    ap.add_argument(
        "--subset", choices=("smoke",), help="only evals/smoke_subset.json items"
    )
    ap.add_argument(
        "--cheap",
        action="store_true",
        help="preset: --subset smoke, VERIFY_MODEL=openai:gpt-4o-mini unless set. Directional only.",
    )
    args = ap.parse_args()
    if args.cheap:
        args.subset = args.subset or "smoke"
        os.environ.setdefault("VERIFY_MODEL", "openai:gpt-4o-mini")
    items = json.loads((HERE / "risk_tier_set.json").read_text())
    if args.subset:
        smoke = set(json.loads((HERE / "smoke_subset.json").read_text())["risk_tier"])
        items = [i for i in items if i["id"] in smoke]
    if args.only:
        only = set(args.only.split(","))
        items = [i for i in items if i["id"] in only]

    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush
    captured: dict = {}
    real_decide = graph_module.pipeline.decide_step
    real_understand = graph_module.understand_query
    real_generate = graph_module.pipeline.generate_step

    def cap_decide(sess, query, stored, cv, chat_id, retrieved, generated, **kw):
        captured["fused"] = retrieved.fused
        captured["cfg"] = retrieved.retrieval_config + kw.get("path_tag", "")
        return real_decide(sess, query, stored, cv, chat_id, retrieved, generated, **kw)

    def cap_understand(q, extractor=None):
        u = real_understand(q, extractor)
        captured["understanding"] = u
        return u

    def cap_generate(query, fused, **kw):
        step = real_generate(query, fused, **kw)
        captured.setdefault("drafts", []).append(step.answer_text)
        return step

    graph_module.pipeline.decide_step = cap_decide
    graph_module.understand_query = cap_understand
    graph_module.pipeline.generate_step = cap_generate
    flags = {
        "agentic": config.agentic_rag_enabled(),
        "risk_tier_framing": config.risk_tier_framing_enabled(),
        "clarify": config.clarify_followup_enabled(),
        "verify_model": config.verify_model(),
        "subset": args.subset,
    }
    rows: list[dict] = []

    def dump(extra: dict | None = None) -> None:
        # Written after every draw, not only at the end: a dropped pooler
        # connection during a long run lost 39 completed draws on 23 Sep 2026.
        if args.json:
            args.json.write_text(
                json.dumps(
                    {
                        "flags": flags,
                        "repeats": args.repeats,
                        "rows": rows,
                        **(extra or {}),
                    },
                    indent=1,
                    default=str,
                )
            )

    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        user = AppUser(email=f"risk-tier-eval-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        print(
            f"flags {flags}  env {os.environ.get('APP_ENV', 'dev')}  items {len(items)}  repeats {args.repeats}"
        )
        for it in items:
            for draw in range(1, args.repeats + 1):
                chat = ChatSession(
                    user_id=user.id, corpus_version_id=cv.id, title="eval"
                )
                session.add(chat)
                session.flush()
                captured.clear()
                res = generate_grounded_answer(
                    session, it["question"], cv.id, chat.id, max_output_tokens=800
                )
                session.flush()
                fused = captured.get("fused", [])
                ctx = [f.result.citation_id for f in fused]
                a = res.answer
                abst = is_abstention(a)
                named = [] if abst or res.clarifying else references_in(a)
                gold = it["gold_citation_ids"]
                gold_named = [g for g in gold if any(_covers(n, g) for n in named)]
                stretched = [
                    n
                    for n in named
                    if any(n.startswith(p) for p in it["forbidden_prefixes"])
                ]
                not_in_ctx = (
                    [] if abst or res.clarifying else missing_references(a, fused)
                )
                u = captured.get("understanding")
                row = {
                    "id": it["id"],
                    "bucket": it["bucket"],
                    "draw": draw,
                    "question": it["question"],
                    "understood": bool(u and u.applies),
                    "search_terms": list(u.search_terms) if u else [],
                    "cfg": captured.get("cfg", ""),
                    "context_ids": ctx,
                    "gold_recall": context_recall(ctx, gold) if gold else None,
                    "abstained": abst,
                    "clarifying": bool(res.clarifying),
                    "route": bool(res.system_description),
                    "named": named,
                    "gold_named": gold_named,
                    "stretched": stretched,
                    "not_in_context": not_in_ctx,
                    "leaks": [] if abst else verdict_leaks(a),
                    "honest_phrase": bool(HONEST.search(a)) if not abst else False,
                    "general_named": [
                        n
                        for n in named
                        if any(_covers(n, g) for g in it.get("general_ids", []))
                    ],
                    "drafts": [
                        d[:120] if d else None for d in captured.get("drafts", [])
                    ],
                    "answer": a[:400],
                }
                rows.append(row)
                dump()
                print(
                    f"  {it['id']} d{draw} {it['bucket']:<13} understood={row['understood']} recall={row['gold_recall']} abst={abst} route={row['route']} named={named[:4]} gold_named={gold_named} stretch={stretched} not_in_ctx={not_in_ctx} leaks={len(row['leaks'])}"
                )
                if not abst:
                    print(f"      A: {a[:230]!r}")
                if u:
                    print(f"      terms: {list(u.search_terms)}")

        # ---- gates ----
        n = args.repeats
        by = defaultdict(list)
        for r in rows:
            by[r["id"]].append(r)
        absolute = {
            "verdict leaks": sum(bool(r["leaks"]) for r in rows),
            "stretched to a forbidden provision": sum(
                bool(r["stretched"]) for r in rows
            ),
            "named a provision not in context": sum(
                bool(r["not_in_context"]) for r in rows
            ),
            "high_risk item not grounded on its gold": sum(
                not (r["gold_named"] and not r["abstained"] and r["gold_recall"] == 1.0)
                for r in rows
                if r["bucket"] == "high_risk"
            ),
            "law_silent item answered or naming a provision": sum(
                (not r["abstained"]) or bool(r["named"]) or not r["route"]
                for r in rows
                if r["bucket"] == "law_silent"
            ),
        }
        print("\n== ABSOLUTE (summed over all draws, must be 0) ==")
        for k, v in absolute.items():
            print(f"  {'ok  ' if v == 0 else 'FAIL'} {v:>2}  {k}")
        abs_ok = all(v == 0 for v in absolute.values())

        print(f"\n== VALUE (per item, majority of {n} draws) ==")
        value_ok = True

        def rep(label, item, oks):
            nonlocal value_ok
            p = sum(oks) * 2 > n
            value_ok &= p
            print(f"  {'ok  ' if p else 'FAIL'} {sum(oks)}/{n}  {label} [{item}]")

        for i, rs in by.items():
            b = rs[0]["bucket"]
            if b == "transparency":
                rep(
                    "answers naming the transparency provision",
                    i,
                    [bool(r["gold_named"]) and not r["abstained"] for r in rs],
                )
            if b == "not_listed":
                rep(
                    "honest answer, no stretch (not the bare abstention)",
                    i,
                    [
                        not r["abstained"]
                        and not r["clarifying"]
                        and not r["stretched"]
                        for r in rs
                    ],
                )
            if b == "prohibited":
                rep(
                    "answers naming the prohibited-practice provision",
                    i,
                    [bool(r["gold_named"]) and not r["abstained"] for r in rs],
                )
        print(
            f"\nABSOLUTE {'PASSED' if abs_ok else 'FAILED'}   VALUE {'PASSED' if value_ok else 'FAILED'}"
        )

        print("\n== per bucket ==")
        for b in (
            "transparency",
            "not_listed",
            "high_risk",
            "law_silent",
            "prohibited",
        ):
            rs = [r for r in rows if r["bucket"] == b]
            if not rs:
                continue
            print(
                f"  {b:<13} draws={len(rs)} answered={sum(not r['abstained'] for r in rs)} abstained={sum(r['abstained'] for r in rs)} gold_in_context={sum(r['gold_recall'] == 1.0 for r in rs)}/{sum(r['gold_recall'] is not None for r in rs)} gold_named={sum(bool(r['gold_named']) for r in rs)} general_named={sum(bool(r['general_named']) for r in rs)} honest_phrase={sum(r['honest_phrase'] for r in rs)} stretched={sum(bool(r['stretched']) for r in rs)} leaks={sum(bool(r['leaks']) for r in rs)}"
            )
        dump({"absolute": absolute, "complete": True})
    finally:
        graph_module.pipeline.decide_step = real_decide
        graph_module.understand_query = real_understand
        graph_module.pipeline.generate_step = real_generate
        session.commit = real_commit
        session.rollback()
        session.close()


if __name__ == "__main__":
    main()
