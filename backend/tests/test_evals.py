import json
import math
from pathlib import Path

import pytest

from app.generation.answer import ABSTENTION_TEXT
from evals.run_eval import (
    abstention_correct,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k_hit():
    assert recall_at_k(["art_1", "art_2", "art_3"], "art_2") == 1.0


def test_recall_at_k_miss():
    assert recall_at_k(["art_1", "art_2", "art_3"], "art_9") == 0.0


def test_reciprocal_rank_first_position():
    assert reciprocal_rank(["art_1", "art_2", "art_3"], "art_1") == 1.0


def test_reciprocal_rank_second_position():
    assert reciprocal_rank(["art_1", "art_2", "art_3"], "art_2") == pytest.approx(0.5)


def test_reciprocal_rank_absent():
    assert reciprocal_rank(["art_1", "art_2", "art_3"], "art_9") == 0.0


def test_abstention_correct_correctly_abstained():
    assert abstention_correct(ABSTENTION_TEXT, [], expected_abstention=True) is True


def test_abstention_correct_incorrectly_abstained_when_should_have_answered():
    assert abstention_correct(ABSTENTION_TEXT, [], expected_abstention=False) is False


def test_abstention_correct_correctly_answered():
    assert (
        abstention_correct(
            "A real grounded answer.", ["citation"], expected_abstention=False
        )
        is True
    )


def test_abstention_correct_incorrectly_answered_when_should_have_abstained():
    assert (
        abstention_correct(
            "A real grounded answer.", ["citation"], expected_abstention=True
        )
        is False
    )


def test_ndcg_at_k_rank_one_is_perfect():
    # With one relevant doc, IDCG is 1, so gold at rank 1 scores exactly 1.0.
    assert ndcg_at_k(["art_1", "art_2"], "art_1") == 1.0


def test_ndcg_at_k_discounts_by_rank():
    # rank 3 -> 1/log2(4) = 0.5
    assert ndcg_at_k(["a", "b", "art_1"], "art_1") == pytest.approx(0.5)


def test_ndcg_at_k_absent_is_zero():
    assert ndcg_at_k(["a", "b", "c"], "art_1") == 0.0


def test_ndcg_at_k_respects_the_depth_cutoff():
    # Gold sits at rank 8, beyond k=5, so it earns nothing at that depth -
    # this is the boundary that distinguishes nDCG@10 from nDCG@5.
    retrieved = [f"other_{i}" for i in range(7)] + ["art_1"]
    assert ndcg_at_k(retrieved, "art_1", k=5) == 0.0
    assert ndcg_at_k(retrieved, "art_1", k=10) == pytest.approx(1 / math.log2(9))


def test_aggregate_average_recall_across_fixture():
    recalls = [1.0, 0.0, 1.0, 1.0]
    assert sum(recalls) / len(recalls) == pytest.approx(0.75)


# --- agentic four-bucket set (evals/agentic_set.json) ------------------------

AGENTIC_SET = Path(__file__).resolve().parents[1] / "evals" / "agentic_set.json"
BUCKETS = {"single_hop", "multi_turn", "multi_hop", "unanswerable"}


def _agentic_items():
    return json.loads(AGENTIC_SET.read_text())


def test_agentic_set_ids_unique_and_buckets_known():
    items = _agentic_items()
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    assert {i["bucket"] for i in items} == BUCKETS
    for i in items:
        assert i["id"].startswith("ag_")
        assert i["source"], i["id"]


def test_agentic_set_gold_matches_answerability():
    for i in _agentic_items():
        if i["expected_abstention"]:
            assert i["gold_citation_ids"] == [], i["id"]
        else:
            assert i["gold_citation_ids"], i["id"]
        assert isinstance(i["history"], list)
        for turn in i["history"]:
            assert len(turn) == 2 and turn[0] in ("user", "assistant"), i["id"]


def test_agentic_set_multi_hop_needs_two_provisions_and_multi_turn_has_history():
    for i in _agentic_items():
        if i["bucket"] == "multi_hop":
            assert len(i["gold_citation_ids"]) >= 2, i["id"]
        if i["bucket"] == "multi_turn":
            assert i["history"], i["id"]
        if i["bucket"] == "single_hop":
            assert i["history"] == [], i["id"]


def test_agentic_set_no_em_dash():
    assert "\u2014" not in AGENTIC_SET.read_text()
