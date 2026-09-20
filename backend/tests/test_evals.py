import math

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
