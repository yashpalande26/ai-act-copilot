"""Follow-up rewriting eval: does rewriting "and for deployers?" into a
standalone question get the right provision in front of the generator?

Retrieval-only, deliberately: "correct citation" here means the expected
provision is inside the top-15 context slice the generator receives (the
production retrieval path: vector + BM25, RRF 0.4/0.6, breadth 25, actor
prior, slice 15), which is what the rewrite can change. Whether gpt-4o then
cites it is the existing generation eval's job and is unchanged by this work.
Recall@5 is printed alongside for comparability with run_eval.py.

Printed per category and pooled:
  baseline      retrieval on the raw follow-up
  rewrite       retrieval on the rewritten query (or the original when the
                rewrite was not applied: no history, pass-through, guard)
  hallucinated  rewrites the entity guard rejected (gate: 0), with the terms
  idempotence   already_standalone cases returned unchanged
  off_corpus    the rewrite must not manufacture an Act question; top vector
                similarity is shown (refusal itself is decided downstream and
                is exercised by the live smoke test)
  regression    the realistic golden set, each question sent as a follow-up
                after an unrelated exchange: pass-through rate and recall
                with vs without the rewriter (gate: unchanged)

VALIDITY: the follow-up set was written by the same person who wrote the
prompt and is anchored on golden-set citations; it cannot see real
conversations. Numbers are provisional until real follow-ups are added.

Paid: one gpt-4o-mini call per sequence and per regression question, plus
query embeddings. No gpt-4o calls.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.models import CorpusVersion
from app.db.session import SessionLocal
from app.generation.answer import (
    RETRIEVAL_CANDIDATE_BREADTH,
    RETRIEVAL_LEXICAL_WEIGHT,
    RETRIEVAL_VECTOR_WEIGHT,
    _lexical_leg,
)
from app.generation.rewrite import rewrite_followup
from app.retrieval.actor import (
    ACTOR_MISMATCH_FACTOR,
    apply_actor_prior,
    detect_query_actor,
)
from app.retrieval.search import rrf_rank_and_fuse, vector_search

SET_PATH = Path(__file__).resolve().parent / "followup_set.json"
GOLDEN_PATH = Path(__file__).resolve().parent / "golden_set_realistic.yaml"
CONTEXT = 15
# v1: follow-ups as first written, which turned out to carry the target
# provision's own key nouns (the baseline already retrieves them). v2: the same
# 18 targets asked the way people actually follow up ("And for admissions?"),
# which cannot be retrieved without the conversation. Both are reported; the
# value gate is applied to the pooled union.
V1_CATEGORIES = ("pronoun_ellipsis", "topic_continuation", "entity_trap")
V2_CATEGORIES = ("terse_pronoun", "terse_continuation", "terse_entity_trap")
FOLLOWUP_CATEGORIES = V1_CATEGORIES + V2_CATEGORIES
UNRELATED_EXCHANGE = [
    (
        "user",
        "Who can submit applications for participation in AI regulatory sandboxes?",
    ),
    ("assistant", "Article 58(2)(b) sets who may apply to participate in a sandbox."),
]
ASSUMED_PRICE = (0.15, 0.60)  # USD per 1M tokens, gpt-4o-mini, as recalled; verify


def production_retrieval(session, query: str, cv_id: int) -> tuple[list[str], float]:
    """Mirror of generate_grounded_answer's retrieval block. Returns the
    citation ids in final order and the top vector similarity."""
    vec = vector_search(
        session, query, cv_id, top_k=RETRIEVAL_CANDIDATE_BREADTH, min_similarity=0.3
    )
    lex, _ = _lexical_leg(session, query, cv_id)
    fused = rrf_rank_and_fuse(
        vec,
        lex,
        vector_weight=RETRIEVAL_VECTOR_WEIGHT,
        lexical_weight=RETRIEVAL_LEXICAL_WEIGHT,
        top_k=RETRIEVAL_CANDIDATE_BREADTH,
    )
    fused = apply_actor_prior(fused, detect_query_actor(query), ACTOR_MISMATCH_FACTOR)
    top_sim = max((r.similarity for r in vec), default=0.0)
    return [f.result.citation_id for f in fused], top_sim


def hit(ids: list[str], expected: str, k: int) -> bool:
    return expected in ids[:k]


def pct(n: int, d: int) -> str:
    return f"{n}/{d}" + (f" ({100 * n / d:.0f}%)" if d else "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--skip-regression", action="store_true")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    cases = json.loads(SET_PATH.read_text())
    if args.limit:
        cases = cases[: args.limit]
    session = SessionLocal()
    cv = (
        session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
        .scalars()
        .first()
    )
    if cv is None:
        sys.exit("no corpus_version")

    tok_in = tok_out = 0
    rows = []
    print(
        "PROVISIONAL: authored follow-up set, blind to real conversations (see docstring)."
    )
    print(f"corpus {cv.consolidated_date}  cases {len(cases)}  context slice {CONTEXT}")
    for c in cases:
        history = [tuple(t) for t in c["history"]]
        rw = rewrite_followup(history, c["followup"])
        tok_in += rw.prompt_tokens or 0
        tok_out += rw.completion_tokens or 0
        base_ids, base_sim = production_retrieval(session, c["followup"], cv.id)
        rw_ids, rw_sim = production_retrieval(session, rw.query, cv.id)
        exp = c["expected_citation_id"]
        row = {
            "id": c["id"],
            "category": c["category"],
            "followup": c["followup"],
            "rewritten": rw.query,
            "applied": rw.applied,
            "introduced": list(rw.introduced),
            "base_hit15": bool(exp) and hit(base_ids, exp, CONTEXT),
            "rw_hit15": bool(exp) and hit(rw_ids, exp, CONTEXT),
            "base_hit5": bool(exp) and hit(base_ids, exp, 5),
            "rw_hit5": bool(exp) and hit(rw_ids, exp, 5),
            "base_top_sim": round(base_sim, 3),
            "rw_top_sim": round(rw_sim, 3),
            "tokens": [rw.prompt_tokens, rw.completion_tokens],
        }
        rows.append(row)
        flag = "GUARD" if rw.introduced else ("rw " if rw.applied else "pass")
        print(
            f"  {c['id']} [{c['category'][:10]:10}] {flag}  base@15={'Y' if row['base_hit15'] else 'n'}"
            f" rw@15={'Y' if row['rw_hit15'] else 'n'}  -> {rw.query[:90]!r}"
            + (f"  introduced={rw.introduced}" if rw.introduced else "")
        )

    def block(label: str, sub: list[dict]) -> None:
        n = len(sub)
        print(f"\n== {label}: {n} sequences ==")
        print(
            f"  correct citation in context (top {CONTEXT}): baseline {pct(sum(r['base_hit15'] for r in sub), n)}"
            f"  ->  with rewrite {pct(sum(r['rw_hit15'] for r in sub), n)}"
        )
        print(
            f"  recall@5:                              baseline {pct(sum(r['base_hit5'] for r in sub), n)}"
            f"  ->  with rewrite {pct(sum(r['rw_hit5'] for r in sub), n)}"
        )
        print(
            f"  rewrites applied {sum(r['applied'] for r in sub)}   guard rejections {sum(bool(r['introduced']) for r in sub)}"
        )

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    for cat in FOLLOWUP_CATEGORIES:
        if by_cat.get(cat):
            block(cat, by_cat[cat])
    block(
        "POOLED v1 keyword-rich follow-ups (no headroom: baseline already retrieves)",
        [r for r in rows if r["category"] in V1_CATEGORIES],
    )
    block(
        "POOLED v2 context-dependent follow-ups",
        [r for r in rows if r["category"] in V2_CATEGORIES],
    )
    pooled = [r for r in rows if r["category"] in FOLLOWUP_CATEGORIES]
    block("POOLED ALL follow-ups (value gate)", pooled)

    guard = [(r["id"], r["introduced"]) for r in rows if r["introduced"]]
    print(
        f"\n  HALLUCINATED-ENTITY REWRITES (guard rejections, all categories): {len(guard)}   gate: 0"
    )
    for g in guard:
        print(f"    {g[0]}: {g[1]}")

    std = by_cat.get("already_standalone", [])
    unchanged = sum(
        1 for r in std if not r["applied"] and r["rewritten"] == r["followup"]
    )
    print(
        f"  IDEMPOTENCE (already standalone returned unchanged): {pct(unchanged, len(std))}"
    )
    for r in std:
        if r["applied"]:
            print(f"    changed: {r['id']}: {r['rewritten']!r}")

    off = by_cat.get("off_corpus", [])
    print(
        f"  OFF-CORPUS follow-ups left alone (no Act question manufactured): {pct(sum(1 for r in off if not r['applied']), len(off))}"
    )
    for r in off:
        print(
            f"    {r['id']}: applied={r['applied']} top_sim raw {r['base_top_sim']} / after {r['rw_top_sim']}  {r['rewritten'][:70]!r}"
        )

    reg = None
    if not args.skip_regression:
        golden = [
            g
            for g in json.loads(GOLDEN_PATH.read_text())
            if not g["expected_abstention"]
        ]
        same = 0
        raw_hits = rw_hits = 0
        changed = []
        for g in golden:
            rw = rewrite_followup(UNRELATED_EXCHANGE, g["question"])
            tok_in += rw.prompt_tokens or 0
            tok_out += rw.completion_tokens or 0
            raw_ids, _ = production_retrieval(session, g["question"], cv.id)
            rw_ids = (
                raw_ids
                if not rw.applied
                else production_retrieval(session, rw.query, cv.id)[0]
            )
            same += not rw.applied
            raw_hits += hit(raw_ids, g["expected_citation_id"], 5)
            rw_hits += hit(rw_ids, g["expected_citation_id"], 5)
            if rw.applied:
                changed.append((g["id"], g["question"], rw.query))
        reg = {
            "n": len(golden),
            "passthrough": same,
            "raw_recall5": raw_hits,
            "rw_recall5": rw_hits,
            "changed": changed,
        }
        print(
            f"\n== SINGLE-TURN REGRESSION (realistic golden set as a follow-up after an unrelated exchange): {len(golden)} questions =="
        )
        print(f"  pass-through unchanged: {pct(same, len(golden))}")
        print(
            f"  recall@5 without rewriter {pct(raw_hits, len(golden))}   with rewriter {pct(rw_hits, len(golden))}   gate: unchanged"
        )
        for cid, q, rq in changed:
            print(f"    rewritten: {cid}: {q[:70]!r} -> {rq[:70]!r}")

    est = (tok_in * ASSUMED_PRICE[0] + tok_out * ASSUMED_PRICE[1]) / 1e6
    print(
        f"\nrewrite tokens in {tok_in} / out {tok_out} (~${est:.4f} at assumed list prices; embeddings extra, negligible)"
    )
    session.close()
    if args.json:
        args.json.write_text(json.dumps({"rows": rows, "regression": reg}, indent=2))
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
