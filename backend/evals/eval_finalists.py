"""Finalist pass: generation + LLM judge across three retrieval settings.

MEASUREMENT ONLY. Production defaults are read, never written; every swept
value is passed as an argument.

WHY THIS DOES NOT CALL generate_grounded_answer
-----------------------------------------------
generate_grounded_answer ALWAYS calls _persist_turn, which commits Message and
Citation rows. There is no flag to disable it (write_trace=False only
suppresses query_trace/retrieval_trace), and modifying production code is out
of scope. So the generation half is replicated here WITHOUT persistence.

The replication is deliberately faithful. It reuses the production objects
rather than restating them, so it cannot drift:
  SYSTEM_PROMPT, CHAT_MODEL, temperature=0   imported from answer.py
  _build_user_prompt                          imported, not reimplemented
  ABSTENTION_TEXT + .strip() comparison       imported, same post-LLM check
  max_tokens omitted when unset               same conditional as production
The ONLY behavioural difference is that nothing is written to the database.
Retrieval is the real vector_search / bm25_search / rrf_rank_and_fuse.

Judge scores come from a single run and carry LLM variance. Treat small gaps
between settings as noise.

    python -m evals.eval_finalists
"""

import json
import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import CorpusVersion
from app.db.session import SessionLocal
from app.generation.answer import (
    ABSTENTION_TEXT,
    CHAT_MODEL,
    SYSTEM_PROMPT,
    _build_user_prompt,
)
from app.ingestion.embedder import _get_client
from app.retrieval.search import bm25_search, rrf_rank_and_fuse, vector_search
from evals.judge import judge_answer_relevance, judge_faithfulness, mean_score

EVALS = Path(__file__).resolve().parent

# (label, breadth, context_slice)
SETTINGS = [
    ("F1", 10, 5),
    ("F2", 10, 10),
    ("F3", 25, 15),
]

# Held at production values.
VECTOR_WEIGHT = 0.4
LEXICAL_WEIGHT = 0.6
MIN_SIMILARITY = 0.3
RRF_K = 60
MAX_OUTPUT_TOKENS = 800  # config.MAX_OUTPUT_TOKENS, what /ask passes

HARD_SAMPLE_N = 20
HARD_SAMPLE_SEED = 42  # same sample across all three settings


def retrieve(session, question, cv_id, breadth, slice_n):
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
        top_k=breadth,
    )
    return fused[:slice_n]


def generate_no_persist(session, question, cv_id, breadth, slice_n):
    """Production generation minus the database writes. Returns
    (answer_text, citations, abstained)."""
    fused = retrieve(session, question, cv_id, breadth, slice_n)
    if not fused:
        return ABSTENTION_TEXT, [], True

    prompt = _build_user_prompt(question, fused)
    response = _get_client().chat.completions.create(
        model=CHAT_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    answer_text = response.choices[0].message.content

    # Same post-LLM abstention rule as production: a verbatim refusal drops
    # citations, so an abstained turn cannot appear to cite anything.
    if answer_text.strip() == ABSTENTION_TEXT:
        return ABSTENTION_TEXT, [], True
    return answer_text, [f.result for f in fused], False


def main() -> None:
    enum = yaml.safe_load((EVALS / "golden_set_enumeration.yaml").read_text())
    hard_all = [
        e
        for e in json.loads((EVALS / "golden_set_hard.yaml").read_text())
        if not e["expected_abstention"]
    ]
    rng = random.Random(HARD_SAMPLE_SEED)
    hard = (
        sorted(rng.sample(hard_all, HARD_SAMPLE_N), key=lambda e: e["id"])
        if len(hard_all) > HARD_SAMPLE_N
        else hard_all
    )

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

        print(
            f"held fixed: v={VECTOR_WEIGHT}/l={LEXICAL_WEIGHT}  "
            f"min_similarity={MIN_SIMILARITY}  rrf_k={RRF_K}  "
            f"max_output_tokens={MAX_OUTPUT_TOKENS}"
        )
        print(
            f"hard sample: {len(hard)} of {len(hard_all)} "
            f"(seed {HARD_SAMPLE_SEED}, identical across settings)"
        )
        print("persistence DISABLED: no _persist_turn, no trace, zero DB writes\n")

        results = {}
        for label, breadth, slice_n in SETTINGS:
            print(
                f"running {label} (breadth={breadth}, slice={slice_n})…",
                file=sys.stderr,
            )

            # ---- A. enumeration tier -----------------------------------
            per_q, contam_total = [], 0
            enum_detail = []
            for e in enum:
                ans, cites, abstained = generate_no_persist(
                    session, e["question"], cv.id, breadth, slice_n
                )
                cited = [c.citation_id for c in cites]
                gold = e.get("gold") or []
                forb = set(e.get("forbidden") or [])
                ur = len([g for g in gold if g in cited]) / len(gold)
                contam = [f for f in forb if f in cited]
                per_q.append(ur)
                contam_total += len(contam)
                enum_detail.append((e["id"], ur, len(contam), abstained))

            # ---- B. hard set, judged -----------------------------------
            faith, rel, abstentions = [], [], 0
            for e in hard:
                ans, cites, abstained = generate_no_persist(
                    session, e["question"], cv.id, breadth, slice_n
                )
                if abstained:
                    abstentions += 1
                    continue  # judging a fixed refusal measures nothing
                faith.append(judge_faithfulness(ans, [c.chunk_text for c in cites]))
                rel.append(judge_answer_relevance(e["question"], ans))

            results[label] = {
                "breadth": breadth,
                "slice": slice_n,
                "enum_mean": sum(per_q) / len(per_q),
                "enum_per_q": per_q,
                "enum_detail": enum_detail,
                "enum_contam": contam_total,
                "faith": mean_score(faith),
                "rel": mean_score(rel),
                "n_judged": len(faith),
                "abstention_rate": abstentions / len(hard),
                "parse_failures": sum(1 for r in faith + rel if r.score == 0),
            }

        # ---------------- comparison table ----------------------------
        print("=" * 108)
        print("FINALIST COMPARISON")
        print("=" * 108)
        print(f"{'metric':<38}" + "".join(f"{lab:<22}" for lab, _, _ in SETTINGS))
        print("-" * 108)

        def row(label, fn, fmt="{:.3f}"):
            print(
                f"{label:<38}"
                + "".join(
                    f"{fmt.format(fn(results[lab])):<22}" for lab, _, _ in SETTINGS
                )
            )

        row("breadth / slice", lambda r: f"{r['breadth']} / {r['slice']}", "{}")
        print()
        print("A. ENUMERATION TIER (5 queries)")
        row("  mean used_recall", lambda r: r["enum_mean"])
        for i, e in enumerate(enum):
            row(
                f"    {e['id'].replace('enum_', '')}", lambda r, i=i: r["enum_per_q"][i]
            )
        row("  used_contamination (count)", lambda r: r["enum_contam"], "{}")
        print()
        print(f"B. HARD SET, LLM-JUDGED ({len(hard)} entries)")
        row("  faithfulness (mean 1-5)", lambda r: r["faith"])
        row("  answer_relevance (mean 1-5)", lambda r: r["rel"])
        row("  abstention rate", lambda r: r["abstention_rate"])
        row(
            "  judged / parse failures",
            lambda r: f"{r['n_judged']} / {r['parse_failures']}",
            "{}",
        )

        print("\nJudge scores are a SINGLE run and carry LLM variance.")
        print("Differences smaller than roughly 0.2 on a 1-5 scale should be")
        print("treated as noise, not signal.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
