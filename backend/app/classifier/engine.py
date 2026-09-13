from app.classifier.models import (
    ClassificationResult,
    RiskTier,
    SystemDescription,
    UseCase,
)

_POINT_5_USE_CASES = {
    UseCase.CREDITWORTHINESS_SCORING,
    UseCase.CREDIT_SCORE_ESTABLISHMENT,
    UseCase.LIFE_HEALTH_INSURANCE_PRICING,
}


def classify(system: SystemDescription) -> ClassificationResult:
    # Rule 1: explicit fraud-detection carve-out from Annex III, point 5(b)
    if system.use_case == UseCase.FINANCIAL_FRAUD_DETECTION:
        return ClassificationResult(
            risk_tier=RiskTier.MINIMAL_RISK,
            triggering_article=None,
            rationale=(
                "Financial fraud detection is explicitly carved out of Annex III, "
                "point 5(b) and is not classified as high-risk."
            ),
        )

    # Rule 2: creditworthiness / credit score, natural persons -> high-risk
    if (
        system.use_case
        in (UseCase.CREDITWORTHINESS_SCORING, UseCase.CREDIT_SCORE_ESTABLISHMENT)
        and system.affects_natural_persons
    ):
        return ClassificationResult(
            risk_tier=RiskTier.HIGH_RISK,
            triggering_article="Annex III, point 5(b)",
            rationale=(
                "Evaluates the creditworthiness or establishes the credit score of "
                "natural persons, triggering Annex III, point 5(b)."
            ),
        )

    # Rule 3: life/health insurance pricing, natural persons -> high-risk
    if (
        system.use_case == UseCase.LIFE_HEALTH_INSURANCE_PRICING
        and system.affects_natural_persons
    ):
        return ClassificationResult(
            risk_tier=RiskTier.HIGH_RISK,
            triggering_article="Annex III, point 5(c)",
            rationale=(
                "Used for risk assessment and pricing in relation to natural persons "
                "for life and health insurance, triggering Annex III, point 5(c)."
            ),
        )

    # Rule 4: same point-5 use cases, but not natural persons -> minimal risk
    if system.use_case in _POINT_5_USE_CASES:
        return ClassificationResult(
            risk_tier=RiskTier.MINIMAL_RISK,
            triggering_article=None,
            rationale=(
                "Annex III, point 5 applies to natural persons; this system does "
                "not affect natural persons (e.g. corporate/B2B use), so no "
                "high-risk trigger applies."
            ),
        )

    # Rule 5: no point-5 trigger in v1 scope
    return ClassificationResult(
        risk_tier=RiskTier.MINIMAL_RISK,
        triggering_article=None,
        rationale=(
            "No Annex III point-5 trigger matched this use case; v1 scope covers "
            "only the financial-services slice of point 5."
        ),
    )
