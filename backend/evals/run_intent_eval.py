"""Intent gate and clarifying follow-up evals, through generate_grounded_answer
(the graph) with the flags as set in the environment. Nothing persists.

    AGENTIC_RAG=1 INTENT_GATE=1 python evals/run_intent_eval.py --intent --json out.json
    AGENTIC_RAG=1 CLARIFY_FOLLOWUP=1 python evals/run_intent_eval.py --clarify --json out.json

Intent set: sequences of messages in one chat; per message the expected lane,
an introduced name to persist, or a name a later reply must contain.
Reported: routing accuracy per bucket, every message with its assigned lane,
social replies checked for legal content (no provision named, no legal
category), offtopic answered count (gate 0), disguised-legal misroutes
(gate 0), name recall across turns, verdict leaks (gate 0).

Clarify set (ADR-24): a plain-language description, then the reply the user
would give to a clarifying question. The reply is sent only if a clarifying
question was asked. Buckets: underspecified (must ask, then ground on the
second pass), area_only (an area of use but no function: either grounds on
turn 1 or asks and grounds on the second pass), law_silent (may ask; after the reply must route with no
provision asserted), already_clear (must not ask; grounds directly), offtopic
(chat lane; never fires), drift (informational: a drifted reply goes through
the normal path once, no second question). Reported: every generated question
with the leak-detector and legal-term verdict, per-bucket fire and ground
counts, and the non-compensatory gates.

NOTE: in production, ask.py answers bare greetings with the scope notice
before the graph (is_trivial_input); this runner calls the graph directly, so
the intent node sees every message.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import re

from sqlalchemy import select

from app import config
from app.db.models import AppUser, ChatSession, CorpusVersion
from app.db.session import SessionLocal
from app.generation import graph as graph_module
from app.generation.answer import generate_grounded_answer, is_abstention
from app.generation.clarify import check_question

# Legal content a social reply must not contain (the copilot may name its
# subject, the EU AI Act; it may not state anything about the law).
SOCIAL_LEGAL = re.compile(
    r"\b(?:article|annex|high[- ]risk|prohibited|obligation\w*|deployer|provider|gpai|conformity)\b",
    re.IGNORECASE,
)
from app.generation.chat_lane import legal_statements
from app.generation.understand import verdict_leaks
from app.generation.verify import references_in
from evals.metrics import context_recall

HERE = Path(__file__).resolve().parent


def lane_of(cfg: str) -> str:
    if "guard=injection" in cfg:
        return "blocked"
    if "lane=chat->rag" in cfg:
        return "rag"
    if "lane=chat" in cfg:
        return "chat"
    if (
        "intent=on_topic" in cfg
        and "CHAT_LANE" in os.environ
        and os.environ["CHAT_LANE"] == "1"
    ):
        return "rag"
    if "intent=social" in cfg:
        return "social"
    if "intent=offtopic" in cfg:
        return "offtopic"
    return "on_topic"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--intent", action="store_true")
    ap.add_argument("--clarify", action="store_true")
    ap.add_argument("--chat", action="store_true")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--only", help="comma-separated item ids (clarify mode)")
    args = ap.parse_args()
    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush
    captured: dict = {}
    real_retrieve = graph_module.pipeline.retrieve_step
    real_decide = graph_module.pipeline.decide_step

    def cap_retrieve(sess, query, cv, **kw):
        captured["retrieve_calls"] = captured.get("retrieve_calls", 0) + 1
        return real_retrieve(sess, query, cv, **kw)

    def cap_decide(sess, query, stored, cv, chat_id, retrieved, generated, **kw):
        captured["cfg"] = retrieved.retrieval_config + kw.get("path_tag", "")
        captured["context_ids"] = [f.result.citation_id for f in retrieved.fused]
        return real_decide(sess, query, stored, cv, chat_id, retrieved, generated, **kw)

    real_chat = graph_module.chat_reply
    real_guard = graph_module.injection_check
    real_generate = graph_module.pipeline.generate_step

    def cap_generate(query, fused, **kw):
        step = real_generate(query, fused, **kw)
        captured.setdefault("drafts", []).append(step.answer_text)
        return step

    def cap_chat(history, message, user_name=None, extractor=None):
        captured["chat_calls"] = captured.get("chat_calls", 0) + 1
        res = real_chat(history, message, user_name, extractor)
        captured["chat_result"] = res
        return res

    def cap_guard(message, extractor=None):
        res = real_guard(message, extractor)
        captured["guard"] = res
        return res

    graph_module.chat_reply = cap_chat
    graph_module.injection_check = cap_guard
    graph_module.pipeline.retrieve_step = cap_retrieve
    graph_module.pipeline.decide_step = cap_decide
    graph_module.pipeline.generate_step = cap_generate
    out: dict = {
        "flags": {
            "intent": config.intent_gate_enabled(),
            "clarify": config.clarify_followup_enabled(),
            "agentic": config.agentic_rag_enabled(),
        }
    }
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        user = AppUser(email=f"intent-eval-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        print(f"flags {out['flags']}  env {os.environ.get('APP_ENV', 'dev')}")

        def turn(chat, text):
            captured.clear()
            res = generate_grounded_answer(
                session, text, cv.id, chat.id, max_output_tokens=800
            )
            session.flush()
            session.refresh(chat)
            return res, dict(captured)

        if args.intent:
            items = json.loads((HERE / "intent_set.json").read_text())
            rows = []
            print("\n== INTENT: every message and its lane ==")
            for it in items:
                chat = ChatSession(
                    user_id=user.id, corpus_version_id=cv.id, title="eval"
                )
                session.add(chat)
                session.flush()
                for k, t in enumerate(it["turns"]):
                    res, cap = turn(chat, t["text"])
                    lane = lane_of(cap.get("cfg", ""))
                    a = res.answer
                    social_legal = lane == "social" and (
                        bool(references_in(a)) or bool(SOCIAL_LEGAL.search(a))
                    )
                    row = {
                        "id": it["id"],
                        "bucket": it["bucket"],
                        "turn": k + 1,
                        "text": t["text"],
                        "expected_lane": t["lane"],
                        "lane": lane,
                        "correct": lane == t["lane"],
                        "answered": not is_abstention(a) and not res.social,
                        "social": res.social,
                        "abstained": is_abstention(a),
                        "leaks": verdict_leaks(a),
                        "social_legal_content": social_legal,
                        "retrieve_calls": cap.get("retrieve_calls", 0),
                        "name_saved": chat.display_name,
                        "name_expected": t.get("name"),
                        "recall_expected": t.get("recall_name"),
                        "name_recalled": (t.get("recall_name") in a)
                        if t.get("recall_name")
                        else None,
                        "answer": a[:160],
                    }
                    rows.append(row)
                    print(
                        f"  {it['id']} t{k + 1} [{t['lane']:>8} -> {lane:<8}] {'ok ' if row['correct'] else 'MIS'} retrieves={row['retrieve_calls']} | {t['text'][:55]!r} -> {a[:90]!r}"
                    )
            by = defaultdict(lambda: [0, 0])
            for r in rows:
                by[r["bucket"]][0] += r["correct"]
                by[r["bucket"]][1] += 1
            print("\n== INTENT: routing accuracy per bucket ==")
            for b, (c, n) in by.items():
                print(f"  {b:<18} {c}/{n}")
            print(
                f"  offtopic answered (gate 0): {sum(r['answered'] for r in rows if r['expected_lane'] == 'offtopic')}"
            )
            print(
                f"  disguised-legal misrouted (gate 0): {sum(not r['correct'] for r in rows if r['bucket'] == 'disguised_legal')}"
            )
            print(
                f"  social replies with legal content (gate 0): {sum(r['social_legal_content'] for r in rows)}"
            )
            print(
                f"  social or offtopic lane that retrieved (gate 0): {sum(r['retrieve_calls'] > 0 for r in rows if r['lane'] != 'on_topic')}"
            )
            print(
                f"  names persisted: {[(r['id'], r['name_saved']) for r in rows if r['name_expected']]}"
            )
            print(
                f"  name recalled on the later turn: {[(r['id'], r['name_recalled']) for r in rows if r['recall_expected']]}"
            )
            print(f"  verdict leaks (gate 0): {sum(bool(r['leaks']) for r in rows)}")
            out["intent"] = rows

        if args.chat:
            items = json.loads((HERE / "chat_lane_set.json").read_text())
            rows = []
            print("\n== CHAT LANE: every message and its lane ==")
            for it in items:
                chat = ChatSession(
                    user_id=user.id, corpus_version_id=cv.id, title="eval"
                )
                session.add(chat)
                session.flush()
                for k, tn in enumerate(it["turns"]):
                    res, cap = turn(chat, tn["text"])
                    cfg = cap.get("cfg", "")
                    lane = lane_of(cfg)
                    a = res.answer
                    chat_lane_turn = lane in ("chat", "blocked")
                    cr = cap.get("chat_result")
                    row = {
                        "id": it["id"],
                        "bucket": it["bucket"],
                        "turn": k + 1,
                        "text": tn["text"],
                        "expected_lane": tn["lane"],
                        "lane": lane,
                        "correct": lane == tn["lane"]
                        or (tn["lane"] == "chat_or_rag" and lane in ("chat", "rag")),
                        "answered": not is_abstention(a),
                        "leaks": verdict_leaks(a),
                        "leak_fired_on_chat": bool(verdict_leaks(a))
                        if chat_lane_turn
                        else None,
                        "legal_statements": legal_statements(a)
                        if chat_lane_turn
                        else [],
                        "chat_model_calls": cap.get("chat_calls", 0),
                        "handoff_query": getattr(cr, "handoff_query", None)
                        if cr
                        else None,
                        "guard_blocked": bool(
                            getattr(cap.get("guard"), "blocked", False)
                        ),
                        "retrieve_calls": cap.get("retrieve_calls", 0),
                        "name_saved": chat.display_name,
                        "name_expected": tn.get("name"),
                        "recall_expected": tn.get("recall_name"),
                        "name_recalled": (tn.get("recall_name") in a)
                        if tn.get("recall_name")
                        else None,
                        "expect_found": (tn["expect"].lower() in a.lower())
                        if tn.get("expect")
                        else None,
                        "recall": context_recall(
                            cap.get("context_ids", []), tn["gold_citation_ids"]
                        )
                        if tn.get("gold_citation_ids")
                        else None,
                        "cited": len(res.citations),
                        "answer": a[:200],
                    }
                    rows.append(row)
                    print(
                        f"  {it['id']} t{k + 1} [{tn['lane']:>7} -> {lane:<7}] {'ok ' if row['correct'] else 'MIS'} chat_calls={row['chat_model_calls']} leak={row['leak_fired_on_chat']} legal={len(row['legal_statements'])} | {tn['text'][:50]!r} -> {a[:80]!r}"
                    )
                    if row["handoff_query"]:
                        print(f"      handoff: {row['handoff_query']!r}")
            by = defaultdict(lambda: [0, 0])
            for r_ in rows:
                by[r_["bucket"]][0] += r_["correct"]
                by[r_["bucket"]][1] += 1
            print("\n== CHAT LANE: gates ==")
            for b, (c_, n) in by.items():
                print(f"  {b:<14} routed {c_}/{n}")
            chat_rows = [r_ for r_ in rows if r_["lane"] == "chat"]
            print(
                f"  legal statements by the chat lane (gate 0): {sum(bool(r_['legal_statements']) for r_ in chat_rows)}"
            )
            print(
                f"  verdict leaks, all items (gate 0): {sum(bool(r_['leaks']) for r_ in rows)}"
            )
            print(
                f"  injection attempts passed to the chat model (gate 0): {sum(r_['chat_model_calls'] for r_ in rows if r_['bucket'] == 'injection')}"
            )
            print(
                f"  injection attempts blocked: {sum(r_['lane'] == 'blocked' for r_ in rows if r_['bucket'] == 'injection')}/{sum(1 for r_ in rows if r_['bucket'] == 'injection')}"
            )
            funnel = [
                r_
                for r_ in rows
                if r_["bucket"] == "idea_funnel" and r_["expected_lane"] == "rag"
            ]
            print(
                f"  Act questions funneled to rag: {sum(r_['lane'] == 'rag' for r_ in funnel)}/{len(funnel)}; grounded on gold: {sum(r_.get('recall') == 1.0 for r_ in funnel)}/{len(funnel)}; cited answers: {sum(r_['cited'] > 0 for r_ in funnel)}/{len(funnel)}"
            )
            print(
                f"  general chat answered naturally: {sum(r_['answered'] for r_ in rows if r_['bucket'] == 'general_chat')}/{sum(1 for r_ in rows if r_['bucket'] == 'general_chat')}; expected facts found: {[(r_['id'], r_['expect_found']) for r_ in rows if r_['expect_found'] is not None]}"
            )
            print(
                f"  name persisted and recalled: {[(r_['id'], r_['name_saved'], r_['name_recalled']) for r_ in rows if r_['recall_expected']]}"
            )
            print(
                f"  chat or blocked lanes that retrieved (gate 0): {sum(r_['retrieve_calls'] > 0 for r_ in rows if r_['lane'] in ('chat', 'blocked'))}"
            )
            out["chat"] = rows

        if args.clarify:
            items = json.loads((HERE / "clarify_set.json").read_text())
            if args.only:
                only = set(args.only.split(","))
                items = [it for it in items if it["id"] in only]
            rows = []
            print("\n== CLARIFY: every sequence ==")
            for it in items:
                chat = ChatSession(
                    user_id=user.id, corpus_version_id=cv.id, title="eval"
                )
                session.add(chat)
                session.flush()
                res1, cap1 = turn(chat, it["description"])
                asked = res1.clarifying
                q = res1.answer if asked else None
                cfg1 = cap1.get("cfg", "")
                drafts1 = cap1.get("drafts", [])
                row = {
                    "id": it["id"],
                    "bucket": it["bucket"],
                    "description": it["description"],
                    "turn1_cfg": cfg1,
                    "turn1_lane": lane_of(cfg1),
                    "turn1_understood": "understand=applied" in cfg1,
                    "turn1_generator_abstained": bool(drafts1)
                    and drafts1[-1] is not None
                    and is_abstention(drafts1[-1]),
                    "turn1_abstained": is_abstention(res1.answer),
                    "turn1_recall": context_recall(
                        cap1.get("context_ids", []), it["gold_citation_ids"]
                    )
                    if it["gold_citation_ids"]
                    else None,
                    "turn1_route": res1.system_description,
                    "turn1_named": references_in(res1.answer)
                    if not is_abstention(res1.answer) and not asked
                    else [],
                    "turn1_leaks": verdict_leaks(res1.answer) if not asked else [],
                    "asked": asked,
                    "question": q,
                    "question_check": check_question(q) if q else None,
                    "question_leaks": verdict_leaks(q) if q else [],
                    "pending_marker": chat.pending_clarification,
                    "turn1_answer": res1.answer[:200],
                }
                # The fire rule, checked per item: asked only if understood
                # as a system description AND the generator's draft abstained.
                row["fired_correctly"] = (not asked) or (
                    row["turn1_understood"] and row["turn1_generator_abstained"]
                )
                if asked:
                    res2, cap2 = turn(chat, it["reply"])
                    ctx = cap2.get("context_ids", [])
                    cfg2 = cap2.get("cfg", "")
                    row.update(
                        turn2_cfg=cfg2,
                        turn2_lane=lane_of(cfg2),
                        turn2_abstained=is_abstention(res2.answer),
                        turn2_recall=context_recall(ctx, it["gold_citation_ids"])
                        if it["gold_citation_ids"]
                        else None,
                        turn2_named=references_in(res2.answer)
                        if not is_abstention(res2.answer)
                        else [],
                        turn2_route=res2.system_description,
                        turn2_clarifying=res2.clarifying,
                        turn2_leaks=verdict_leaks(res2.answer),
                        marker_cleared=chat.pending_clarification is None,
                        turn2_answer=res2.answer[:200],
                    )
                rows.append(row)
                print(
                    f"  {it['id']} {it['bucket']:<14} turn1: lane={row['turn1_lane']} understood={row['turn1_understood']} gen_abstained={row['turn1_generator_abstained']} asked={asked} recall={row['turn1_recall']} named={row['turn1_named'][:2]}"
                )
                if asked:
                    print(
                        f"     Q: {q!r}\n     check={row['question_check']} leaks={row['question_leaks']}\n     turn2: lane={row['turn2_lane']} abstained={row['turn2_abstained']} recall={row['turn2_recall']} named={row['turn2_named'][:3]} route={row['turn2_route']} clarifying_again={row['turn2_clarifying']} marker_cleared={row['marker_cleared']}\n     A2: {row['turn2_answer'][:160]!r}"
                    )
                elif not row["turn1_abstained"]:
                    print(f"     A1: {row['turn1_answer'][:160]!r}")

            def bucket(name):
                return [r for r in rows if r["bucket"] == name]

            def grounded_on(r, key):
                return r.get(key + "_recall") == 1.0 and not r.get(key + "_abstained")

            print("\n== CLARIFY: every generated question ==")
            for r in rows:
                if r["asked"]:
                    print(
                        f"  {r['id']:<6} check={r['question_check'] or 'ok':<8} leaks={len(r['question_leaks'])}  {r['question']!r}"
                    )
            print("\n== CLARIFY: per bucket (fired / grounded) ==")
            for b in (
                "underspecified",
                "area_only",
                "law_silent",
                "already_clear",
                "offtopic",
                "drift",
            ):
                rs = bucket(b)
                if not rs:
                    continue
                fired = sum(r["asked"] for r in rs)
                g1 = sum(grounded_on(r, "turn1") for r in rs)
                g2 = sum(r["asked"] and grounded_on(r, "turn2") for r in rs)
                routed2 = sum(
                    bool(r.get("turn2_route")) and bool(r.get("turn2_abstained"))
                    for r in rs
                )
                lanes = [r["turn1_lane"] for r in rs]
                print(
                    f"  {b:<14} n={len(rs)} fired={fired} grounded_turn1={g1} grounded_turn2={g2} routed_after_reply={routed2} turn1_lanes={lanes}"
                )
            under = bucket("underspecified")
            silent = bucket("law_silent")
            clear = bucket("already_clear")
            off = bucket("offtopic")
            gates = {
                "verdict leaks, all items and questions": sum(
                    bool(r["turn1_leaks"])
                    or bool(r["question_leaks"])
                    or bool(r.get("turn2_leaks"))
                    for r in rows
                ),
                "law_silent stretched to a provision": sum(
                    bool(r["turn1_named"]) or bool(r.get("turn2_named")) for r in silent
                ),
                "law_silent not routed after the sequence": sum(
                    not (
                        (r.get("turn2_route") and r.get("turn2_abstained"))
                        if r["asked"]
                        else (r["turn1_route"] and r["turn1_abstained"])
                    )
                    for r in silent
                ),
                "fired on something other than an abstaining system description": sum(
                    not r["fired_correctly"] for r in rows
                ),
                "questions failing the check after display": sum(
                    bool(r["question_check"]) for r in rows if r["asked"]
                ),
                "second clarification asked": sum(
                    bool(r.get("turn2_clarifying")) for r in rows
                ),
                "marker left set after the reply": sum(
                    r["asked"] and not r.get("marker_cleared") for r in rows
                ),
                "underspecified not asked": sum(not r["asked"] for r in under),
                "underspecified not grounded on the second pass": sum(
                    not (r["asked"] and grounded_on(r, "turn2")) for r in under
                ),
                "area_only neither grounded on turn 1 nor asked-then-grounded": sum(
                    not (
                        grounded_on(r, "turn2")
                        if r["asked"]
                        else grounded_on(r, "turn1")
                    )
                    for r in bucket("area_only")
                ),
                "already_clear asked": sum(r["asked"] for r in clear),
                "already_clear not grounded on turn 1": sum(
                    not grounded_on(r, "turn1") for r in clear
                ),
                "offtopic fired": sum(r["asked"] for r in off),
            }
            print("\n== CLARIFY: gates (every count must be 0) ==")
            for k, v in gates.items():
                print(f"  {'ok  ' if v == 0 else 'FAIL'} {v:>2}  {k}")
            print(
                f"  GATE {'PASSED' if all(v == 0 for v in gates.values()) else 'FAILED'}"
            )
            out["clarify"] = rows
            out["clarify_gates"] = gates
        if args.json:
            args.json.write_text(json.dumps(out, indent=1, default=str))
    finally:
        graph_module.chat_reply = real_chat
        graph_module.injection_check = real_guard
        graph_module.pipeline.retrieve_step = real_retrieve
        graph_module.pipeline.decide_step = real_decide
        graph_module.pipeline.generate_step = real_generate
        session.commit = real_commit
        session.rollback()
        session.close()


if __name__ == "__main__":
    main()
