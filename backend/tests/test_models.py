import pytest
from pydantic import ValidationError

from app.classifier.models import (
    ClassificationResult,
    RiskTier,
    SystemDescription,
    UseCase,
)


def test_system_description_constructs():
    sd = SystemDescription(
        intended_purpose="Score loan applicants' creditworthiness",
        use_case=UseCase.CREDITWORTHINESS_SCORING,
        affects_natural_persons=True,
    )
    assert sd.use_case == UseCase.CREDITWORTHINESS_SCORING
    assert sd.affects_natural_persons is True


def test_classification_result_constructs():
    result = ClassificationResult(
        risk_tier=RiskTier.HIGH_RISK,
        triggering_article="Annex III",
        rationale="Used for creditworthiness scoring of natural persons.",
    )
    assert result.risk_tier == RiskTier.HIGH_RISK
    assert result.triggering_article == "Annex III"


def test_system_description_rejects_empty_intended_purpose():
    with pytest.raises(ValidationError):
        SystemDescription(
            intended_purpose="",
            use_case=UseCase.OTHER,
            affects_natural_persons=False,
        )
