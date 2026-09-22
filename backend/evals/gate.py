"""The non-compensatory gate every agentic node must pass against the plain
baseline, and the equivalence check Stage 0 uses.

    python evals/gate.py baseline.json candidate.json
    python evals/gate.py off.json on.json --equivalence

Both files are the JSON written by evals/run_agentic_eval.py --json.

GATE (a node may ship only if ALL hold; no metric can buy another):
  must improve   faithfulness, context_recall, abstention_f1 (macro of
                 F1_ans and F1_ref): candidate > baseline + min_improvement.
                 A metric already at its ceiling (1.0) cannot be beaten;
                 holding it counts as passing that check (ceiling_holds).
  no regression  citation_accuracy: candidate >= baseline - tolerance.
min_improvement and tolerance default to 0 and are Yash's to set from the
measured run-to-run variance (ADR-7 rule); the defaults make the gate the
strictest reading, not a chosen one.

EQUIVALENCE (Stage 0): the deterministic metrics must be identical (context
recall and precision per trace, predicted abstention per trace, citation
accuracy per trace) and the judged metrics are printed side by side; the
model at temperature 0 is not deterministic, so those are compared, not
asserted.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

MUST_IMPROVE = ("faithfulness", "context_recall", "abstention_f1")
NO_REGRESS = ("citation_accuracy",)
DETERMINISTIC_PER_TRACE = (
    "context_recall",
    "context_precision",
    "predicted_abstention",
    "citation_accuracy",
)


@dataclass
class Check:
    metric: str
    rule: str
    baseline: float | None
    candidate: float | None
    passed: bool
    note: str = ""


@dataclass
class GateResult:
    passed: bool
    checks: list[Check] = field(default_factory=list)

    def table(self) -> str:
        rows = [f"{'metric':<20}{'rule':<14}{'baseline':>10}{'candidate':>11}  verdict"]
        for c in self.checks:
            b = "n/a" if c.baseline is None else f"{c.baseline:.3f}"
            k = "n/a" if c.candidate is None else f"{c.candidate:.3f}"
            v = "PASS" if c.passed else "FAIL"
            rows.append(f"{c.metric:<20}{c.rule:<14}{b:>10}{k:>11}  {v} {c.note}")
        rows.append(f"GATE: {'PASS' if self.passed else 'FAIL'} (non-compensatory)")
        return "\n".join(rows)


def gate(
    baseline: dict[str, float | None],
    candidate: dict[str, float | None],
    *,
    must_improve: tuple[str, ...] = MUST_IMPROVE,
    no_regress: tuple[str, ...] = NO_REGRESS,
    min_improvement: float = 0.0,
    tolerance: float = 0.0,
    ceiling: float = 1.0,
    ceiling_holds: bool = True,
) -> GateResult:
    checks: list[Check] = []
    for m in must_improve:
        b, c = baseline.get(m), candidate.get(m)
        if b is None or c is None:
            checks.append(Check(m, "must improve", b, c, False, "undefined"))
            continue
        if ceiling_holds and b >= ceiling and c >= b:
            checks.append(Check(m, "must improve", b, c, True, "held at ceiling"))
            continue
        checks.append(Check(m, "must improve", b, c, c > b + min_improvement))
    for m in no_regress:
        b, c = baseline.get(m), candidate.get(m)
        if b is None or c is None:
            checks.append(Check(m, "no regression", b, c, False, "undefined"))
            continue
        checks.append(Check(m, "no regression", b, c, c >= b - tolerance))
    return GateResult(passed=all(k.passed for k in checks), checks=checks)


@dataclass
class EquivalenceResult:
    identical: bool
    differences: list[str]
    compared: int

    def table(self) -> str:
        head = (
            f"EQUIVALENCE: {'IDENTICAL' if self.identical else 'DIFFERENT'} "
            f"({self.compared} traces x {len(DETERMINISTIC_PER_TRACE)} deterministic fields)"
        )
        return "\n".join([head, *self.differences])


def equivalence(a: dict, b: dict) -> EquivalenceResult:
    ra = {t["id"]: t for t in a["traces"]}
    rb = {t["id"]: t for t in b["traces"]}
    diffs: list[str] = []
    if set(ra) != set(rb):
        diffs.append(f"trace ids differ: {sorted(set(ra) ^ set(rb))}")
    for tid in sorted(set(ra) & set(rb)):
        for f in DETERMINISTIC_PER_TRACE:
            if ra[tid].get(f) != rb[tid].get(f):
                diffs.append(f"{tid}.{f}: {ra[tid].get(f)!r} vs {rb[tid].get(f)!r}")
        if ra[tid].get("context_ids") != rb[tid].get("context_ids"):
            diffs.append(f"{tid}.context_ids differ")
    return EquivalenceResult(not diffs, diffs, len(set(ra) & set(rb)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("baseline", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--equivalence", action="store_true")
    ap.add_argument("--min-improvement", type=float, default=0.0)
    ap.add_argument("--tolerance", type=float, default=0.0)
    args = ap.parse_args()
    a = json.loads(args.baseline.read_text())
    b = json.loads(args.candidate.read_text())
    if args.equivalence:
        print(equivalence(a, b).table())
    print("pooled:")
    res = gate(
        a["pooled"],
        b["pooled"],
        min_improvement=args.min_improvement,
        tolerance=args.tolerance,
    )
    print(res.table())
    for bucket in sorted(a.get("buckets", {})):
        if bucket in b.get("buckets", {}):
            print(f"\nbucket {bucket}:")
            print(gate(a["buckets"][bucket], b["buckets"][bucket]).table())
    if not args.equivalence:
        sys.exit(0 if res.passed else 1)


if __name__ == "__main__":
    main()
