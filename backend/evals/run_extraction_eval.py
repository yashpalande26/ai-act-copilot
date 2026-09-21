"""Extraction eval: prose -> ExtractedAnswers -> Answers, scored per field
against hand-written gold, per category, plus end-to-end verdict match.

VALIDITY, STATED UP FRONT (CLAUDE.md invariant 2): the set was written by the
same people who wrote the prompt. It cannot see real-user phrasing, other
languages, or systems outside our own mental model. Numbers are provisional
until real descriptions are added as a fourth category.

What is scored, per case, over the fields the user would SEE for the gold
answers (visible_fields):
  correct          gold known, predicted the same value with a verified quote
  wrong            gold known, predicted a different value
  missed           gold known, predicted unknown (cheap: the user fills it in)
  correct_unknown  gold unknown, predicted unknown
  false_inference  gold unknown, predicted a value (the dangerous error)
Separately:
  quote failures   inferred values whose quote was missing or not a verbatim
                   substring of the description; the mapper downgrades these
                   to unknown, so they are counted here as hard failures AND
                   then scored as "unknown" above
  legal-five       false-inference rate restricted to the five legal
                   characterisation fields (verdict-flipping if guessed)
  verdict A        engine headline on the mapped answers as-is
  verdict B        engine headline after unknowns are replaced by gold
                   (what happens after the user confirms; the product metric)

Usage:
  python evals/run_extraction_eval.py [--limit N] [--category C] [--model KEY]
                                      [--json out.json]
Paid: one call per case (default openai:gpt-4o-mini). Prints measured tokens.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assessment.engine import assess
from app.assessment.report import _Corpus
from app.assessment.schema import Answers
from app.db.session import SessionLocal
from app.extraction.extraction import (
    LEGAL_CHARACTERISATION_FIELDS,
    ExtractedAnswers,
    build_system_prompt,
    prompt_version,
    to_answers,
    visible_fields,
)
from app.extraction.llm import get_extractor

SET_PATH = Path(__file__).resolve().parent / "extraction_set.json"

# USD per 1M tokens (input, output). List prices as recalled on 21 Sep 2026;
# verify against the provider's pricing page before quoting a figure anywhere.
# Tokens are the measured number; cost is an estimate from these constants.
ASSUMED_PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00)}

CATEGORIES = ("explicit", "partial", "adversarial")


def _eq(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return sorted(a) == sorted(b)
    return a == b


def score_case(case: dict, mapped) -> dict:
    gold = Answers(**case["gold"])
    unknown = set(case["gold_unknown"])
    seen = visible_fields(gold)
    per_field: dict[str, str] = {}
    for f in sorted(seen):
        pred_unknown = mapped.provenance[f] == "unknown"
        if f in unknown:
            per_field[f] = "correct_unknown" if pred_unknown else "false_inference"
        elif pred_unknown:
            per_field[f] = "missed"
        elif _eq(getattr(mapped.answers, f), getattr(gold, f)):
            per_field[f] = "correct"
        else:
            per_field[f] = "wrong"

    verdict_a = assess(mapped.answers).headline
    confirmed = mapped.answers.model_dump()
    for f, p in mapped.provenance.items():
        if p == "unknown":
            confirmed[f] = getattr(gold, f)
    verdict_b = assess(Answers(**confirmed)).headline

    desc_ci = " ".join(case["description"].split()).lower()

    # Independent audit of every quote the mapper ACCEPTED (gate: "no
    # fabricated quote passes the check"). A second implementation, not a call
    # to verify_quote: strip edge punctuation, collapse whitespace, lowercase,
    # then require a plain substring of the description.
    def independent_ok(q: str) -> bool:
        core = " ".join(q.split()).strip(" .,;:!?\"'“”‘’()[]").lower()
        return bool(core) and core in desc_ci

    fabricated = [f for f, q in mapped.quotes.items() if not independent_ok(q)]

    def reason(q) -> str:
        # "case_only": verbatim apart from letter case (e.g. a lowercased
        # sentence start). Still a hard failure in the mapper; reported apart
        # so a decision to relax the check can be made from numbers.
        if q.reason == "not_verbatim" and " ".join(q.quote.split()).lower() in desc_ci:
            return "case_only"
        return q.reason

    return {
        "id": case["id"],
        "category": case["category"],
        "per_field": per_field,
        "predicted": {
            f: getattr(mapped.answers, f)
            for f, p in mapped.provenance.items()
            if p == "inferred"
        },
        "quotes": mapped.quotes,
        "fabricated_passed": fabricated,
        "quote_failures": [
            {"field": q.field, "quote": q.quote, "reason": reason(q)}
            for q in mapped.quote_failures
        ],
        "expected": case["expected_headline"],
        "verdict_a": verdict_a,
        "verdict_b": verdict_b,
        "match_a": verdict_a == case["expected_headline"],
        "match_b": verdict_b == case["expected_headline"],
    }


def _rate(num: int, den: int) -> str:
    return f"{num}/{den}" + (f" ({100 * num / den:.0f}%)" if den else "")


def summarise(rows: list[dict], label: str) -> None:
    n = len(rows)
    tally: Counter[str] = Counter()
    legal_fi = legal_den = 0
    qf: Counter[str] = Counter()
    for r in rows:
        for f, outcome in r["per_field"].items():
            tally[outcome] += 1
            if f in LEGAL_CHARACTERISATION_FIELDS and outcome in (
                "correct_unknown",
                "false_inference",
            ):
                legal_den += 1
                legal_fi += outcome == "false_inference"
        for q in r["quote_failures"]:
            qf[q["reason"]] += 1
    quote_fail = sum(qf.values())
    accepted = sum(len(r["quotes"]) for r in rows)
    fabricated = sum(len(r.get("fabricated_passed", [])) for r in rows)
    known = tally["correct"] + tally["wrong"] + tally["missed"]
    unk = tally["correct_unknown"] + tally["false_inference"]
    print(f"\n== {label}: {n} cases, {known + unk} visible fields scored ==")
    print(
        f"  gold known   correct {_rate(tally['correct'], known)}  wrong {tally['wrong']}  missed {tally['missed']}"
    )
    print(f"  gold unknown kept unknown {_rate(tally['correct_unknown'], unk)}")
    print(
        f"  FALSE INFERENCE (value where gold is unknown): {_rate(tally['false_inference'], unk)}"
    )
    print(
        f"  FALSE INFERENCE on legal-characterisation fields: {_rate(legal_fi, legal_den)}   target ~0"
    )
    print(
        f"  QUOTE HARD FAILURES: {quote_fail}  (missing {qf['missing']}, not verbatim {qf['not_verbatim']}, case-only {qf['case_only']})"
    )
    print(
        f"  FABRICATED QUOTES THAT PASSED THE CHECK (independent audit of {accepted} accepted quotes): {fabricated}   must be 0"
    )
    print(f"  verdict match A (as mapped): {_rate(sum(r['match_a'] for r in rows), n)}")
    print(
        f"  verdict match B (after unknowns confirmed from gold): {_rate(sum(r['match_b'] for r in rows), n)}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--category", choices=CATEGORIES)
    ap.add_argument("--model", help="registry key, e.g. openai:gpt-4o-mini")
    ap.add_argument("--json", type=Path, help="write per-case results here")
    args = ap.parse_args()

    cases = json.loads(SET_PATH.read_text())
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
    if args.limit:
        cases = cases[: args.limit]

    session = SessionLocal()
    try:
        corpus = _Corpus(session)
        prompt = build_system_prompt(lambda cid: corpus.node(cid, "self"))
        consolidated = str(corpus.version.consolidated_date)
    finally:
        session.close()
    extractor = get_extractor(args.model)
    version = prompt_version(prompt)

    print(
        "PROVISIONAL: authored eval set, blind to real-user phrasing (see module docstring)."
    )
    print(
        f"extractor {extractor.name}   prompt_version {version}   corpus {consolidated}   cases {len(cases)}"
    )

    rows: list[dict] = []
    tokens_in = tokens_out = 0
    latencies: list[int] = []
    refusals = 0
    for c in cases:
        out = extractor.extract(
            system_prompt=prompt, user_text=c["description"], schema=ExtractedAnswers
        )
        tokens_in += out.prompt_tokens or 0
        tokens_out += out.completion_tokens or 0
        latencies.append(out.latency_ms)
        if out.parsed is None:
            refusals += 1
            print(f"  {c['id']}: REFUSED/EMPTY ({out.refusal!r})", file=sys.stderr)
            continue
        mapped = to_answers(out.parsed, c["description"])
        row = score_case(c, mapped)
        row["tokens"] = [out.prompt_tokens, out.completion_tokens]
        # The model's output before mapping, so a downgraded field can still be
        # inspected afterwards (run 2 lacked this and could not say what value
        # sat behind each empty quote).
        row["raw"] = out.parsed.model_dump()
        rows.append(row)
        bad = [
            k for k, v in row["per_field"].items() if v in ("wrong", "false_inference")
        ]
        qf = [q["field"] for q in row["quote_failures"]]
        print(
            f"  {c['id']:6} A={'ok ' if row['match_a'] else 'MISS'} B={'ok ' if row['match_b'] else 'MISS'}"
            f"  wrong/false: {bad or '-'}  quote-fail: {qf or '-'}"
        )

    for cat in CATEGORIES:
        sub = [r for r in rows if r["category"] == cat]
        if sub:
            summarise(sub, cat)
    summarise(rows, "ALL (pooled; read the per-category lines first)")

    # Worst fields across the run, so a prompt fix targets the right field.
    by_field: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        for f, o in r["per_field"].items():
            by_field[f][o] += 1
    print("\n== fields with any wrong / false inference ==")
    for f, cnt in sorted(
        by_field.items(), key=lambda kv: -(kv[1]["wrong"] + kv[1]["false_inference"])
    ):
        if cnt["wrong"] or cnt["false_inference"]:
            print(
                f"  {f:44} wrong {cnt['wrong']:2}  false_inference {cnt['false_inference']:2}  missed {cnt['missed']:2}"
            )

    model_key = extractor.name.split(":", 1)[-1]
    price = ASSUMED_PRICES.get(model_key)
    est = (
        f"~${(tokens_in * price[0] + tokens_out * price[1]) / 1e6:.4f} at assumed list prices"
        if price
        else "no price constant for this model"
    )
    print(
        f"\ncalls {len(cases)}  refusals {refusals}  tokens in {tokens_in} / out {tokens_out}"
        f"  ({est})  latency p50 {sorted(latencies)[len(latencies) // 2] if latencies else 0} ms"
    )

    if args.json:
        args.json.write_text(
            json.dumps(
                {"extractor": extractor.name, "prompt_version": version, "rows": rows},
                indent=2,
            )
        )
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
