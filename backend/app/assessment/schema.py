"""Request and response shapes for /assess. Answers in, a dated report out."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal[
    "provider", "deployer", "importer", "distributor", "authorised_representative"
]

# Sort order for the headline, not a claim that the categories are exclusive:
# a high-risk system can also carry Article 50 duties, and the report lists
# every applicable block regardless of the headline.
Headline = Literal[
    "OUT_OF_SCOPE",
    "PROHIBITED_FLAG",  # matches an Article 5(1) pattern; a red flag, never a verdict
    "HIGH_RISK",  # Article 6(2) via Annex III
    "HIGH_RISK_POSSIBLE",  # Article 6(1) product route; Annex I not in corpus
    "TRANSPARENCY",  # Article 50 obligations, no high-risk match
    "MINIMAL",
]

PROHIBITED_KEYS = ("a", "b", "ba", "bb", "c", "d", "e", "f", "g", "h")


class Answers(BaseModel):
    """Every field is a fact the user attests to. Nothing here is a legal
    conclusion; the engine draws those, and only where the text is literal."""

    # --- scope (Article 2) --------------------------------------------------
    is_ai_system: bool = True  # self-declared against art_3.pt_1 (flag S1)
    personal_non_professional: bool = False  # art_2.par_10
    research_only: bool = False  # art_2.par_6
    pre_market_only: bool = False  # art_2.par_8
    national_security_only: bool = False  # art_2.par_3
    open_source: bool = False  # art_2.par_12, conditional exemption

    # --- roles (Article 3(3)-(7)); several may be true at once (flag R2) -----
    roles: list[Role] = Field(default_factory=list)
    # Article 25(1) reclassification, asked of non-providers (flag R1)
    puts_own_name: bool = False
    substantial_modification: bool = False
    changed_intended_purpose: bool = False

    # --- prohibited practices (Article 5(1)); pattern keys a..h, ba, bb ------
    prohibited_patterns: list[str] = Field(default_factory=list)

    # --- high-risk ----------------------------------------------------------
    product_safety_component: bool = False  # art_6.par_1 route (flag H1)
    annex_iii_point: str | None = None  # e.g. "anx_III.pt_4.sub_a"
    acts_for_public_authority: bool = False  # gates pt_5.sub_a, pt_6, pt_7, pt_8.sub_a
    biometric_verification_only: bool = False  # excludes pt_1.sub_a
    fraud_detection_only: bool = False  # excludes pt_5.sub_b
    relies_on_6_3: bool = False  # never changes the tier (flag H2)
    fria_body: bool = False  # public body / public services / Annex III 5(b),(c)

    # --- transparency (Article 50) -----------------------------------------
    interacts_with_persons: bool = False  # par_1, provider
    generates_synthetic_content: bool = False  # par_2, provider
    deploys_emotion_or_biometric_categorisation: bool = False  # par_3, deployer
    deploys_deep_fakes: bool = False  # par_4, deployer

    # --- general-purpose AI models (flag G1) ---------------------------------
    gpai_provider: bool = False
    gpai_non_eu: bool = False
    gpai_systemic: bool = False

    # --- penalty inputs (Article 99); SME/SMC self-declared (flag N1) -------
    undertaking: bool = True
    turnover_eur: float | None = Field(default=None, ge=0)
    sme_or_startup: bool = False
    smc: bool = False


class ProvisionText(BaseModel):
    citation_id: str
    citation_label: str
    text: str
    children: list["ProvisionText"] = Field(default_factory=list)


class Flag(BaseModel):
    key: str
    provision: ProvisionText


class ObligationGroup(BaseModel):
    key: str
    title: str
    role: str  # "provider" | "deployer" | ... | "all" | "voluntary"
    provisions: list[ProvisionText]
    applies_from: ProvisionText | None = None
    commentary: str | None = None  # the tool's own words, labelled as such in the UI


class PenaltyLine(BaseModel):
    paragraph: ProvisionText
    applicable: bool
    eur_cap: int
    pct_cap: float
    rule: Literal["higher", "lower", "eur_only"]
    rule_basis: list[ProvisionText]  # e.g. art_99.par_6 when "lower"
    ceiling_eur: float | None  # None when turnover is unknown and the rule needs it
    why: str  # which obligations route here, in the tool's words


class Penalties(BaseModel):
    lines: list[PenaltyLine]
    factors: ProvisionText  # art_99.par_7, always shown
    commentary: str


class Decision(BaseModel):
    """The engine's output: ids only, no text. report.py turns it into prose."""

    headline: Headline
    in_scope: bool
    scope_exclusions: list[str]
    open_source_exempt: bool
    roles: list[Role]
    treated_as_provider_basis: list[str]
    prohibited_flags: list[str]  # citation ids under art_5.par_1
    high_risk_basis: str | None  # the matched Annex III id
    annex_iii_note: str | None  # why a selected point did not match
    product_route: bool
    derogation_claimed: bool
    transparency: list[str]  # art_50 paragraph ids
    gpai: list[str]


class AssessmentResult(BaseModel):
    generated_at: datetime
    corpus_version_id: int
    corpus_consolidated_date: str
    decision: Decision
    headline_text: str  # "Based on your answers, your system appears to ..."
    scope: list[ProvisionText]
    role_definitions: list[ProvisionText]
    treated_as_provider: list[ProvisionText]
    prohibited_flags: list[Flag]
    high_risk_basis: ProvisionText | None
    derogation: list[ProvisionText]  # art_6.par_3 (+ par_4, 49(2) if claimed)
    product_route: list[ProvisionText]
    obligations: list[ObligationGroup]
    dates: list[ProvisionText]
    penalties: Penalties
    commentary: list[str]
