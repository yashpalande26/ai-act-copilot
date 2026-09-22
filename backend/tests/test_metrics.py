"""evals/metrics.py and evals/gate.py: literal oracles, never derived with the
code's own formula."""

import pytest

from evals.gate import equivalence, gate
from evals.metrics import (
    abstention_f1,
    citation_accuracy,
    context_precision,
    context_recall,
    inline_mention,
    matches,
    mean,
)

# --- matching -----------------------------------------------------------


def test_matches_exact_and_descendant_only():
    assert matches("art_16.pt_b", "art_16.pt_b")
    assert matches("art_16.pt_b", "art_16")
    assert not matches("art_16", "art_16.pt_b")
    assert not matches(
        "art_160", "art_16"
    )  # prefix without the dot is a different article
    assert not matches("anx_III.pt_4", "anx_II")


# --- recall / precision --------------------------------------------------


def test_context_recall_counts_gold_ids_covered():
    ctx = ["art_1", "art_3.pt_4", "art_9", "art_26.par_2"]
    assert context_recall(ctx, ["art_3.pt_4", "art_26.par_2"]) == 1.0
    assert context_recall(ctx, ["art_3.pt_4", "art_50"]) == 0.5
    assert context_recall(ctx, ["art_50"]) == 0.0
    assert context_recall(ctx, []) is None


def test_context_precision_is_average_precision_over_the_slice():
    # gold at rank 1 only -> 1.0
    assert context_precision(["g", "x", "x"], ["g"]) == 1.0
    # gold at rank 3 only -> precision@3 = 1/3
    assert context_precision(["x", "x", "g"], ["g"]) == pytest.approx(1 / 3)
    # two gold at ranks 1 and 3 -> mean(1/1, 2/3) = 0.8333
    assert context_precision(["g1", "x", "g2"], ["g1", "g2"]) == pytest.approx(
        0.8333, abs=1e-4
    )
    # nothing in the slice -> 0.0, no gold -> None
    assert context_precision(["x", "y"], ["g"]) == 0.0
    assert context_precision(["x"], []) is None


def test_citation_accuracy_fraction_of_gold_cited():
    assert citation_accuracy(["art_16.pt_b", "art_2"], ["art_16.pt_b"]) == 1.0
    assert citation_accuracy(["art_16.pt_b"], ["art_16.pt_b", "art_26"]) == 0.5
    assert citation_accuracy([], ["art_16.pt_b"]) == 0.0
    assert citation_accuracy([], []) is None


# --- inline mention ------------------------------------------------------


def test_inline_mention_matches_article_and_annex_labels():
    assert inline_mention("See Article 16, point (b).", ["art_16.pt_b"]) is True
    assert inline_mention("Article 160 says", ["art_16.pt_b"]) is False
    assert (
        inline_mention("Listed in Annex III, point 4.", ["anx_III.pt_4.sub_a"]) is True
    )
    assert inline_mention("Listed in Annex II.", ["anx_III.pt_4.sub_a"]) is False
    assert inline_mention("anything", []) is None


# --- abstention F1 --------------------------------------------------------


def test_abstention_f1_hand_computed():
    # (expected_abstain, predicted_abstain)
    rows = [
        (False, False),  # answered correctly       ans tp
        (False, False),  # answered correctly       ans tp
        (False, True),  # wrongly refused          ans fn, ref fp
        (True, True),  # refused correctly        ref tp
        (True, False),  # wrongly answered         ref fn, ans fp
    ]
    f = abstention_f1(rows)
    # answered: tp=2 fp=1 fn=1 -> P=2/3 R=2/3 F1=2/3
    assert f.answered.tp == 2 and f.answered.fp == 1 and f.answered.fn == 1
    assert f.f1_ans == pytest.approx(2 / 3)
    # refused: tp=1 fp=1 fn=1 -> F1 = 2*1/(2+1+1) = 0.5
    assert f.f1_ref == pytest.approx(0.5)
    assert f.macro == pytest.approx((2 / 3 + 0.5) / 2)


def test_abstention_f1_undefined_class_is_none_not_zero():
    f = abstention_f1([(False, False), (False, False)])
    assert f.f1_ans == 1.0
    assert f.f1_ref is None
    assert f.macro == 1.0


def test_mean_skips_none():
    assert mean([1.0, None, 0.0]) == 0.5
    assert mean([None]) is None


# --- gate ------------------------------------------------------------------

BASE = {
    "faithfulness": 0.90,
    "context_recall": 0.80,
    "abstention_f1": 0.95,
    "citation_accuracy": 0.85,
}


def test_gate_passes_only_when_every_check_passes():
    better = {
        **BASE,
        "faithfulness": 0.92,
        "context_recall": 0.85,
        "abstention_f1": 0.96,
    }
    assert gate(BASE, better).passed is True


def test_gate_is_non_compensatory():
    # big recall win cannot buy a faithfulness loss
    traded = {**BASE, "context_recall": 1.0, "abstention_f1": 1.0, "faithfulness": 0.89}
    res = gate(BASE, traded)
    assert res.passed is False
    assert [c.metric for c in res.checks if not c.passed] == ["faithfulness"]


def test_gate_citation_regression_fails_even_with_all_improvements():
    regressed = {
        "faithfulness": 0.95,
        "context_recall": 0.9,
        "abstention_f1": 0.99,
        "citation_accuracy": 0.84,
    }
    res = gate(BASE, regressed)
    assert res.passed is False
    assert [c.metric for c in res.checks if not c.passed] == ["citation_accuracy"]


def test_gate_equal_is_not_an_improvement_unless_at_ceiling():
    assert gate(BASE, dict(BASE)).passed is False
    at_ceiling = {**BASE, "abstention_f1": 1.0}
    held = {**at_ceiling, "faithfulness": 0.91, "context_recall": 0.81}
    res = gate(at_ceiling, held)
    assert res.passed is True
    assert [c.note for c in res.checks if c.metric == "abstention_f1"] == [
        "held at ceiling"
    ]
    assert gate(at_ceiling, held, ceiling_holds=False).passed is False


def test_gate_undefined_metric_fails_closed():
    res = gate(BASE, {**BASE, "faithfulness": None})
    assert res.passed is False


def test_gate_min_improvement_and_tolerance():
    slight = {
        **BASE,
        "faithfulness": 0.905,
        "context_recall": 0.805,
        "abstention_f1": 0.955,
    }
    assert gate(BASE, slight).passed is True
    assert gate(BASE, slight, min_improvement=0.01).passed is False
    dip = {**slight, "citation_accuracy": 0.84}
    assert gate(BASE, dip).passed is False
    assert gate(BASE, dip, tolerance=0.02).passed is True


# --- equivalence ------------------------------------------------------------


def _run(**over):
    t = {
        "id": "x",
        "context_recall": 1.0,
        "context_precision": 0.5,
        "predicted_abstention": False,
        "citation_accuracy": 1.0,
        "context_ids": ["a", "b"],
        "faithfulness": 5,
    }
    t.update(over)
    return {"traces": [t]}


def test_equivalence_ignores_judged_fields_and_catches_deterministic_ones():
    assert equivalence(_run(), _run(faithfulness=3)).identical is True
    res = equivalence(_run(), _run(predicted_abstention=True))
    assert res.identical is False
    assert res.differences == ["x.predicted_abstention: False vs True"]
    assert equivalence(_run(), _run(context_ids=["b", "a"])).identical is False
