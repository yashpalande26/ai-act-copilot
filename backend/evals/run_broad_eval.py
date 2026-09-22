"""Broad on-topic questions vs off-topic questions: where does a refusal come
from, and does the fix hold?

Per broad question (retrieval-only unless --generate):
  top_sim      highest cosine similarity among vector-ranked candidates
  gold@25      best rank of a gold provision among the 25 fused candidates
  gold@15      best rank inside the 15-chunk context the generator sees
  pre_llm      the pre-LLM gate fired (no candidate at all)
  class        NOT_RETRIEVED (gold absent from the 25), RETRIEVED_NOT_IN_CONTEXT
               (in 25, outside 15), IN_CONTEXT
With --generate (paid, gpt-4o, ~$0.006 each; nothing persists: the session's
commit is pointed at flush and rolled back):
  answered     the model did not abstain (is_abstention, quote-tolerant)
  gold_cited   answered AND a gold provision is among the returned citations
  bad_articles articles the answer names that are neither cited provisions nor
               named inside a cited chunk's text (must be 0)
Off-topic questions must refuse: by the scope short-circuit, the pre-LLM gate,
or the model. --golden also reports golden-set recall@5/@15 on the production
path for the hard and realistic sets. --anchor-floor sweeps the dense anchor
(-1 disables it), so before/after tables come from the same code.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

import app.generation.answer as answer_module
from app.db.models import AppUser, ChatSession, CorpusVersion
from app.db.session import SessionLocal
from app.generation.answer import (
    DENSE_ANCHOR_FLOOR,
    generate_grounded_answer,
    is_abstention,
    retrieve_candidates,
)
from app.generation.scope import is_trivial_input

HERE = Path(__file__).resolve().parent
CONTEXT = 15
_ART = re.compile(r"\bArticle\s+(\d+[a-z]?)\b", re.IGNORECASE)


def retrieve(session, query: str, cv_id: int, floor: float | None):
    fused, cfg = retrieve_candidates(session, query, cv_id, dense_anchor_floor=floor)
    top_sim = max(
        (f.result.similarity for f in fused if f.vector_rank is not None), default=0.0
    )
    return fused, top_sim, cfg


def gold_rank(ids: list[str], prefixes: list[str]) -> int | None:
    for i, cid in enumerate(ids, start=1):
        if any(cid == p or cid.startswith(p + ".") for p in prefixes):
            return i
    return None


def articles_in(ids: list[str]) -> set[str]:
    out = set()
    for cid in ids:
        m = re.match(r"art_(\d+[a-z]?)", cid)
        if m:
            out.add(m.group(1).lower())
    return out


def pct(n: int, d: int) -> str:
    return f"{n}/{d}" + (f" ({100 * n / d:.0f}%)" if d else "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--generate", action="store_true", help="also run gpt-4o (paid)")
    ap.add_argument(
        "--anchor-floor",
        type=float,
        default=DENSE_ANCHOR_FLOOR,
        help="dense anchor floor; -1 disables",
    )
    ap.add_argument("--golden", action="store_true", help="golden-set recall too")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    floor = None if args.anchor_floor < 0 else args.anchor_floor
    # generate_grounded_answer reads the module default; keep it in step.
    answer_module.DENSE_ANCHOR_FLOOR = floor

    broad = json.loads((HERE / "broad_set.json").read_text())
    off = json.loads((HERE / "offtopic_set.json").read_text())
    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush  # nothing persists
    cv = (
        session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
        .scalars()
        .first()
    )
    user = AppUser(email=f"broad-eval-{uuid4()}@example.com")
    session.add(user)
    session.flush()
    chat = ChatSession(user_id=user.id, corpus_version_id=cv.id, title="eval")
    session.add(chat)
    session.flush()

    print(
        f"corpus {cv.consolidated_date}  context {CONTEXT}  generate={args.generate}  dense_anchor_floor={floor}"
    )
    rows = []
    print("\n== BROAD ON-TOPIC ==")
    for c in broad:
        q = c["question"]
        fused, top_sim, cfg = retrieve(session, q, cv.id, floor)
        ids = [f.result.citation_id for f in fused]
        r25 = gold_rank(ids, c["gold_prefixes"])
        r15 = gold_rank(ids[:CONTEXT], c["gold_prefixes"])
        klass = (
            "IN_CONTEXT"
            if r15
            else ("RETRIEVED_NOT_IN_CONTEXT" if r25 else "NOT_RETRIEVED")
        )
        row = {
            "id": c["id"],
            "question": q,
            "trivial": is_trivial_input(q),
            "top_sim": round(top_sim, 3),
            "gold_at_25": r25,
            "gold_at_15": r15,
            "pre_llm_abstain": not fused,
            "class": klass,
            "anchored": "anchor=dense" in cfg,
            "top3": ids[:3],
        }
        if args.generate and fused:
            res = generate_grounded_answer(
                session, q, cv.id, chat.id, max_output_tokens=800
            )
            cited = [x.citation_id for x in res.citations]
            named = {a.lower() for a in _ART.findall(res.answer)}
            allowed = articles_in(cited) | {
                a.lower() for x in res.citations for a in _ART.findall(x.chunk_text)
            }
            answered = not is_abstention(res.answer)
            row.update(
                answered=answered,
                gold_cited=bool(gold_rank(cited, c["gold_prefixes"])) and answered,
                bad_articles=sorted(named - allowed),
                answer=res.answer[:200],
            )
        rows.append(row)
        gen = (
            f" answered={row.get('answered')} gold_cited={row.get('gold_cited')} bad={row.get('bad_articles')}"
            if args.generate and fused
            else ""
        )
        print(
            f"  {c['id']} {klass:24} sim={row['top_sim']:.3f} gold@25={r25} gold@15={r15}"
            f" anchor={row['anchored']}{gen}  | {q}"
        )

    print("\n== OFF-TOPIC (must refuse) ==")
    off_rows = []
    for c in off:
        q = c["question"]
        if is_trivial_input(q):
            row = {
                "id": c["id"],
                "question": q,
                "refused_by": "scope_short_circuit",
                "refused": True,
            }
        else:
            fused, top_sim, cfg = retrieve(session, q, cv.id, floor)
            row = {
                "id": c["id"],
                "question": q,
                "top_sim": round(top_sim, 3),
                "candidates": len(fused),
                "anchored": "anchor=dense" in cfg,
                "refused_by": "pre_llm" if not fused else None,
                "refused": not fused,
            }
            if args.generate and fused:
                res = generate_grounded_answer(
                    session, q, cv.id, chat.id, max_output_tokens=800
                )
                row["refused"] = is_abstention(res.answer)
                row["refused_by"] = "model" if row["refused"] else "NOT REFUSED"
                row["answer"] = res.answer[:200]
        off_rows.append(row)
        print(
            f"  {c['id']} refused={row['refused']} by={row['refused_by']} sim={row.get('top_sim')} anchor={row.get('anchored')}  | {q}"
        )

    n = len(rows)
    print("\n== SUMMARY ==")
    for k in ("IN_CONTEXT", "RETRIEVED_NOT_IN_CONTEXT", "NOT_RETRIEVED"):
        print(f"  {k:24} {sum(r['class'] == k for r in rows)}/{n}")
    print(
        f"  pre-LLM gate fired on broad: {sum(r['pre_llm_abstain'] for r in rows)}/{n}"
    )
    print(
        f"  anchor fired: broad {sum(r['anchored'] for r in rows)}/{n}, off-topic {sum(bool(r.get('anchored')) for r in off_rows)}/{len(off_rows)}"
    )
    if args.generate:
        print(
            f"  answered {pct(sum(bool(r.get('answered')) for r in rows), n)}   answered WITH gold cited {pct(sum(bool(r.get('gold_cited')) for r in rows), n)}"
            f"   bad-article mentions {sum(len(r.get('bad_articles', [])) for r in rows)}"
        )
    print(
        f"  off-topic refused: {pct(sum(r['refused'] for r in off_rows), len(off_rows))}"
        + (
            ""
            if args.generate
            else "   (retrieval level only; --generate for the model's verdict)"
        )
    )

    golden = None
    if args.golden:
        golden = {}
        for name in ("golden_set_hard.yaml", "golden_set_realistic.yaml"):
            items = [
                g
                for g in json.loads((HERE / name).read_text())
                if not g["expected_abstention"]
            ]
            r5 = r15 = fired = 0
            for g in items:
                fused, _, cfg = retrieve(session, g["question"], cv.id, floor)
                ids = [f.result.citation_id for f in fused]
                r5 += g["expected_citation_id"] in ids[:5]
                r15 += g["expected_citation_id"] in ids[:CONTEXT]
                fired += "anchor=dense" in cfg
            golden[name] = {
                "n": len(items),
                "recall5": r5,
                "recall15": r15,
                "anchor_fired": fired,
            }
            print(
                f"  GOLDEN {name}: n={len(items)} recall@5={r5}/{len(items)} recall@15={r15}/{len(items)} anchor_fired={fired}"
            )

    session.commit = real_commit
    session.rollback()
    session.close()
    if args.json:
        args.json.write_text(
            json.dumps(
                {"floor": floor, "broad": rows, "offtopic": off_rows, "golden": golden},
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
