import os
from unittest.mock import MagicMock

import pytest

from evals import judge as judge_module
from evals.judge import JudgeResult, mean_score, pass_at_4_rate


def _make_llm_response(content: str):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def test_well_formed_response_parses_correctly(monkeypatch):
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _make_llm_response(
        '{"rationale": "All claims are supported.", "score": 4}'
    )
    monkeypatch.setattr(judge_module, "_get_client", lambda: fake_client)

    result = judge_module.judge_faithfulness("An answer.", ["Some context."])

    assert result == JudgeResult(score=4, rationale="All claims are supported.")


def test_malformed_response_is_a_parse_failure_not_a_crash(monkeypatch):
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _make_llm_response(
        "this is not json at all"
    )
    monkeypatch.setattr(judge_module, "_get_client", lambda: fake_client)

    result = judge_module.judge_answer_relevance("A question?", "An answer.")

    assert result.score == 0
    assert result.rationale.startswith("PARSE_FAILURE")


def test_aggregation_excludes_parse_failures_from_denominator():
    results = [
        JudgeResult(score=5, rationale="ok"),
        JudgeResult(score=4, rationale="ok"),
        JudgeResult(score=3, rationale="ok"),
        JudgeResult(score=0, rationale="PARSE_FAILURE: bad json"),
    ]

    # mean over the 3 valid scores (5+4+3)/3 = 4.0, not diluted by the failure
    assert mean_score(results) == pytest.approx(4.0)
    # pass@4 over the 3 valid scores: 2 of 3 are >= 4
    assert pass_at_4_rate(results) == pytest.approx(2 / 3)


def test_aggregation_all_parse_failures_returns_zero_not_a_crash():
    results = [JudgeResult(score=0, rationale="PARSE_FAILURE: x")]
    assert mean_score(results) == 0.0
    assert pass_at_4_rate(results) == 0.0


@pytest.mark.live
def test_judge_integration_real_call_plausible_score():
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not configured")

    result = judge_module.judge_faithfulness(
        answer="The sky is blue.",
        context_chunks=["The sky appears blue due to Rayleigh scattering of sunlight."],
    )

    assert 1 <= result.score <= 5
    assert result.score >= 3
    assert result.rationale
