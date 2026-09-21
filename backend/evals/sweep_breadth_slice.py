"""Breadth x context-slice grid. MEASUREMENT ONLY.

Retrieval layer only. This script never calls generate_grounded_answer, never
calls an LLM, never calls _persist_turn, and writes ZERO database rows: the
only DB traffic is the SELECTs inside vector_search and bm25_search.

Production defaults are read, never written. Every swept value is passed as an
argument, so answer.py's constants are untouched.

Two things verified before writing this, because both would have silently
corrupted the grid:

1. Slice-equality does NOT hold. vector_search applies min_similarity AFTER
   the SQL LIMIT, so a LIMIT 50 query backfills past rows a LIMIT 10 query
   never sees. Retrieving once at depth 50 and slicing would therefore NOT
   reproduce breadth=10. Each breadth is retrieved separately.
   (Slicing the FUSED list for context_slice IS exact, since that is just
   taking the first N of an already-ordered list with no filtering.)

2. Recall@5 / MRR / nDCG@10 are computed on the fused ranking at fixed
   cutoffs, so they depend on breadth ONLY. context_slice cannot move them.
   Table B therefore repeats across the three slices of a given breadth; that
   is the correct result, not a bug.

    python -m evals.sweep_breadth_slice
"""

import json
import math
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import CorpusVersion
from app.db.session import SessionLocal
from app.generation.answer import (
    SYSTEM_PROMPT,
    _build_user_prompt,
)
from app.retrieval.search import bm25_search, rrf_rank_and_fuse, vector_search

EVALS = Path(__file__).resolve().parent

BREADTHS = [10, 25, 50]
SLICES = [5, 10, 15]

# Held fixed at production values. Read, not mutated.
VECTOR_WEIGHT = 0.4
LEXICAL_WEIGHT = 0.6
MIN_SIMILARITY = 0.3
RRF_K = 60


# tiktoken is not installed, so token counts are the standard chars/4
# approximation. It is monotonic in true token count, so cell-to-cell
# comparison (which is what this grid is for) is sound even though absolute
# values carry error. Calibrated against a real query_trace.prompt_tokens
# value at the end of the run.
def approx_tokens(text: str) -> int:
    return round(len(text) / 4)


def load_sets():
    enum = yaml.safe_load((EVALS / "golden_set_enumeration.yaml").read_text())

    def j(name):
        return [
            e
            for e in json.loads((EVALS / name).read_text())
            if not e["expected_abstention"]
        ]

    return {
        "enumeration": enum,
        "easy": j("golden_set.yaml"),
        "hard": j("golden_set_hard.yaml"),
        "realistic": j("golden_set_realistic.yaml"),
    }


def retrieve(session, question, cv_id, breadth):
    """One fused list per (question, breadth), at production weights."""
    v = vector_search(
        session, question, cv_id, top_k=breadth, min_similarity=MIN_SIMILARITY
    )
    b = bm25_search(session, question, cv_id, top_k=breadth)
    fused = rrf_rank_and_fuse(
        v,
        b,
        vector_weight=VECTOR_WEIGHT,
        lexical_weight=LEXICAL_WEIGHT,
        k=RRF_K,
        top_k=breadth,  # keep all fused
    )
    return fused


def recall_at(ids, expected, k):
    return 1.0 if expected in ids[:k] else 0.0


def mrr_at(ids, expected, k):
    for i, c in enumerate(ids[:k], 1):
        if c == expected:
            return 1.0 / i
    return 0.0


def ndcg_at(ids, expected, k):
    for i, c in enumerate(ids[:k], 1):
        if c == expected:
            return 1.0 / math.log2(i + 1)
    return 0.0


def main() -> None:
    sets = load_sets()
    session = SessionLocal()
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        if cv is None:
            print("No corpus_version found.", file=sys.stderr)
            sys.exit(1)

        # ---- retrieve once per (query, breadth) --------------------------
        cache = {}
        for name, entries in sets.items():
            for e in entries:
                for b in BREADTHS:
                    cache[(name, e["id"], b)] = retrieve(
                        session, e["question"], cv.id, b
                    )
            print(
                f"  retrieved {name}: {len(entries)} queries x {len(BREADTHS)} breadths",
                file=sys.stderr,
            )

        print(
            f"held fixed: weights v={VECTOR_WEIGHT}/l={LEXICAL_WEIGHT}  "
            f"min_similarity={MIN_SIMILARITY}  rrf_k={RRF_K}"
        )
        print("retrieval layer only: no generation, no LLM, no DB writes\n")

        # ---- TABLE A: enumeration tier -----------------------------------
        print("=" * 112)
        print("TABLE A - ENUMERATION TIER (context level, deterministic)")
        print("=" * 112)
        enum = sets["enumeration"]
        hdr = f"{'breadth':<9}{'slice':<7}{'mean_ctx_recall':<17}{'contam':<8}{'mean_ctx_tokens':<17}"
        hdr += "".join(f"{e['id'].replace('enum_', ''):<22}" for e in enum)
        print(hdr)
        print("-" * 112)
        tableA = {}
        for b in BREADTHS:
            for sl in SLICES:
                per_q, contam, toks = [], 0, []
                for e in enum:
                    fused = cache[("enumeration", e["id"], b)]
                    ctx = [f.result.citation_id for f in fused[:sl]]
                    gold = e.get("gold") or []
                    forb = set(e.get("forbidden") or [])
                    per_q.append(len([g for g in gold if g in ctx]) / len(gold))
                    contam += len([f for f in forb if f in ctx])
                    prompt = SYSTEM_PROMPT + _build_user_prompt(
                        e["question"], fused[:sl]
                    )
                    toks.append(approx_tokens(prompt))
                mean_r = sum(per_q) / len(per_q)
                mean_t = round(sum(toks) / len(toks))
                tableA[(b, sl)] = (mean_r, contam, mean_t)
                row = f"{b:<9}{sl:<7}{mean_r:<17.3f}{contam:<8}{mean_t:<17}"
                row += "".join(f"{v:<22.3f}" for v in per_q)
                print(row)

        # ---- TABLE B: existing golden sets -------------------------------
        print("\n" + "=" * 112)
        print("TABLE B - EXISTING GOLDEN SETS (ranking metrics, deterministic)")
        print("Recall@5 / MRR / nDCG@10 use fixed cutoffs on the fused ranking, so")
        print("they depend on BREADTH only. Values repeat across slices by definition.")
        print("=" * 112)
        print(
            f"{'breadth':<9}{'slice':<7}"
            + "".join(
                f"{s + ' R@5':<11}{s + ' MRR':<11}{s + ' nDCG':<12}"
                for s in ("easy", "hard", "real")
            )
        )
        print("-" * 112)
        tableB = {}
        for b in BREADTHS:
            cells = {}
            for name in ("easy", "hard", "realistic"):
                rs, ms, ns = [], [], []
                for e in sets[name]:
                    ids = [f.result.citation_id for f in cache[(name, e["id"], b)]]
                    exp = e["expected_citation_id"]
                    rs.append(recall_at(ids, exp, 5))
                    ms.append(mrr_at(ids, exp, 5))
                    ns.append(ndcg_at(ids, exp, 10))
                cells[name] = (sum(rs) / len(rs), sum(ms) / len(ms), sum(ns) / len(ns))
            for sl in SLICES:
                tableB[(b, sl)] = cells
                row = f"{b:<9}{sl:<7}"
                for name in ("easy", "hard", "realistic"):
                    r, m, n = cells[name]
                    row += f"{r:<11.3f}{m:<11.3f}{n:<12.3f}"
                print(row)

        # ---- Pareto front -------------------------------------------------
        print("\n" + "=" * 112)
        print("PARETO FRONT")
        print("=" * 112)
        base_b = BREADTHS[0]
        baseline = tableB[(base_b, SLICES[0])]
        print("no-regression baseline = breadth 10 (current production):")
        for name in ("easy", "hard", "realistic"):
            r, m, n = baseline[name]
            print(f"   {name:<11}R@5={r:.3f}  MRR={m:.3f}  nDCG={n:.3f}")
        print()
        rows = []
        for b in BREADTHS:
            for sl in SLICES:
                mean_r, contam, toks = tableA[(b, sl)]
                cells = tableB[(b, sl)]
                regress = []
                for name in ("easy", "hard", "realistic"):
                    for i, label in enumerate(("R@5", "MRR", "nDCG")):
                        if cells[name][i] < baseline[name][i] - 1e-9:
                            regress.append(f"{name}.{label}")
                rows.append((b, sl, mean_r, contam, toks, regress))
        # Pareto: not dominated on (ctx_recall up, tokens down) among clean cells
        clean = [r for r in rows if not r[5]]
        front = []
        for r in clean:
            if not any(
                o[2] >= r[2] and o[4] <= r[4] and (o[2] > r[2] or o[4] < r[4])
                for o in clean
            ):
                front.append(r)
        print(
            f"{'breadth':<9}{'slice':<7}{'ctx_recall':<13}{'contam':<8}{'tokens':<9}{'regressions':<28}pareto"
        )
        print("-" * 112)
        for b, sl, mean_r, contam, toks, regress in rows:
            on = any(f[0] == b and f[1] == sl for f in front)
            reg = ", ".join(regress) if regress else "none"
            print(
                f"{b:<9}{sl:<7}{mean_r:<13.3f}{contam:<8}{toks:<9}{reg:<28}{'YES' if on else ''}"
            )

        # ---- token approximation calibration -------------------------------
        print("\ntoken figures are chars/4 (tiktoken not installed).")
        print("calibration: a real /ask call for the provider-obligations query at")
        print("slice=5 recorded prompt_tokens=660 in query_trace.")
        fused = cache[("enumeration", "enum_provider_obligations", 10)]
        est = approx_tokens(
            SYSTEM_PROMPT
            + _build_user_prompt(sets["enumeration"][0]["question"], fused[:5])
        )
        print(
            f"this script estimates {est} for the same prompt "
            f"({est / 660:.2f}x actual), so absolute values carry error but the"
        )
        print("ordering across cells, which is what the grid is for, is sound.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
