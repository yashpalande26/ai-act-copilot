from app.classifier.engine import classify
from app.classifier.models import RiskTier, SystemDescription, UseCase


def test_financial_fraud_detection_is_minimal_risk():
    system = SystemDescription(
        intended_purpose="Detect fraudulent transactions",
        use_case=UseCase.FINANCIAL_FRAUD_DETECTION,
        affects_natural_persons=True,
    )
    result = classify(system)
    assert result.risk_tier == RiskTier.MINIMAL_RISK
    assert result.triggering_article is None


def test_creditworthiness_scoring_natural_persons_is_high_risk():
    system = SystemDescription(
        intended_purpose="Score loan applicants",
        use_case=UseCase.CREDITWORTHINESS_SCORING,
        affects_natural_persons=True,
    )
    result = classify(system)
    assert result.risk_tier == RiskTier.HIGH_RISK
    assert result.triggering_article == "Annex III, point 5(b)"


def test_credit_score_establishment_natural_persons_is_high_risk():
    system = SystemDescription(
        intended_purpose="Establish credit scores",
        use_case=UseCase.CREDIT_SCORE_ESTABLISHMENT,
        affects_natural_persons=True,
    )
    result = classify(system)
    assert result.risk_tier == RiskTier.HIGH_RISK
    assert result.triggering_article == "Annex III, point 5(b)"


def test_life_health_insurance_pricing_natural_persons_is_high_risk():
    system = SystemDescription(
        intended_purpose="Price life insurance premiums",
        use_case=UseCase.LIFE_HEALTH_INSURANCE_PRICING,
        affects_natural_persons=True,
    )
    result = classify(system)
    assert result.risk_tier == RiskTier.HIGH_RISK
    assert result.triggering_article == "Annex III, point 5(c)"


def test_point_5_use_case_without_natural_persons_is_minimal_risk():
    system = SystemDescription(
        intended_purpose="Score corporate borrowers' creditworthiness",
        use_case=UseCase.CREDITWORTHINESS_SCORING,
        affects_natural_persons=False,
    )
    result = classify(system)
    assert result.risk_tier == RiskTier.MINIMAL_RISK
    assert result.triggering_article is None


def test_other_use_case_is_minimal_risk():
    system = SystemDescription(
        intended_purpose="Some unrelated AI system",
        use_case=UseCase.OTHER,
        affects_natural_persons=True,
    )
    result = classify(system)
    assert result.risk_tier == RiskTier.MINIMAL_RISK
    assert result.triggering_article is None
