from enum import Enum

from pydantic import BaseModel, Field


class RiskTier(str, Enum):
    PROHIBITED = "PROHIBITED"
    HIGH_RISK = "HIGH_RISK"
    LIMITED_RISK = "LIMITED_RISK"
    MINIMAL_RISK = "MINIMAL_RISK"


class UseCase(str, Enum):
    CREDITWORTHINESS_SCORING = "CREDITWORTHINESS_SCORING"
    CREDIT_SCORE_ESTABLISHMENT = "CREDIT_SCORE_ESTABLISHMENT"
    LIFE_HEALTH_INSURANCE_PRICING = "LIFE_HEALTH_INSURANCE_PRICING"
    FINANCIAL_FRAUD_DETECTION = "FINANCIAL_FRAUD_DETECTION"
    OTHER = "OTHER"


class SystemDescription(BaseModel):
    intended_purpose: str = Field(min_length=1)
    use_case: UseCase
    affects_natural_persons: bool


class ClassificationResult(BaseModel):
    risk_tier: RiskTier
    triggering_article: str | None = None
    rationale: str
