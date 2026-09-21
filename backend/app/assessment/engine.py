"""Deterministic classification. Pure: answers in, citation ids out.

Every branch names the provision it rests on. Where the Act requires a legal
characterisation (is this a "substantial modification"? does the Article 6(3)
derogation apply?) the engine records the user's answer and never decides.
"""

from app.assessment.schema import PROHIBITED_KEYS, Answers, Decision, Role

ANNEX_III_POINTS: tuple[str, ...] = (
    "anx_III.pt_1.sub_a",
    "anx_III.pt_1.sub_b",
    "anx_III.pt_1.sub_c",
    "anx_III.pt_2",
    "anx_III.pt_3.sub_a",
    "anx_III.pt_3.sub_b",
    "anx_III.pt_3.sub_c",
    "anx_III.pt_3.sub_d",
    "anx_III.pt_4.sub_a",
    "anx_III.pt_4.sub_b",
    "anx_III.pt_5.sub_a",
    "anx_III.pt_5.sub_b",
    "anx_III.pt_5.sub_c",
    "anx_III.pt_5.sub_d",
    "anx_III.pt_6.sub_a",
    "anx_III.pt_6.sub_b",
    "anx_III.pt_6.sub_c",
    "anx_III.pt_6.sub_d",
    "anx_III.pt_6.sub_e",
    "anx_III.pt_7.sub_a",
    "anx_III.pt_7.sub_b",
    "anx_III.pt_7.sub_c",
    "anx_III.pt_7.sub_d",
    "anx_III.pt_8.sub_a",
    "anx_III.pt_8.sub_b",
)

# Points whose text applies only to (or on behalf of) public authorities, law
# enforcement, competent authorities or judicial authorities.
AUTHORITY_GATED: frozenset[str] = frozenset(
    {"anx_III.pt_5.sub_a", "anx_III.pt_8.sub_a"}
    | {p for p in ANNEX_III_POINTS if p.startswith(("anx_III.pt_6.", "anx_III.pt_7."))}
)

ART_25_BASIS = (
    ("puts_own_name", "art_25.par_1.pt_a"),
    ("substantial_modification", "art_25.par_1.pt_b"),
    ("changed_intended_purpose", "art_25.par_1.pt_c"),
)

SCOPE_EXCLUSIONS = (
    ("personal_non_professional", "art_2.par_10"),
    ("research_only", "art_2.par_6"),
    ("pre_market_only", "art_2.par_8"),
    ("national_security_only", "art_2.par_3"),
)


def _annex_iii(a: Answers) -> tuple[str | None, str | None]:
    """(matched id, note). The note explains, in the tool's words, why a
    selected point did not match; the report quotes the exclusion text."""
    p = a.annex_iii_point
    if p is None or p not in ANNEX_III_POINTS:
        return None, None
    if p == "anx_III.pt_1.sub_a" and a.biometric_verification_only:
        return None, (
            "You indicated the sole purpose is biometric verification, which "
            "Annex III, point 1(a) expressly excludes."
        )
    if p == "anx_III.pt_5.sub_b" and a.fraud_detection_only:
        return None, (
            "You indicated the system is used for detecting financial fraud, "
            "which Annex III, point 5(b) expressly excludes."
        )
    if p in AUTHORITY_GATED and not a.acts_for_public_authority:
        return None, (
            "The selected Annex III point applies to systems used by, or on "
            "behalf of, the authorities it names; you indicated you are not "
            "such an authority and do not act on one's behalf."
        )
    return p, None


def assess(a: Answers) -> Decision:
    scope_exclusions = [cid for field, cid in SCOPE_EXCLUSIONS if getattr(a, field)]

    prohibited = [
        f"art_5.par_1.pt_{k}" for k in a.prohibited_patterns if k in PROHIBITED_KEYS
    ]

    high_risk_basis, annex_note = _annex_iii(a)
    high_risk = high_risk_basis is not None

    roles: list[Role] = list(dict.fromkeys(a.roles))  # order-preserving dedupe
    treated_as_provider: list[str] = []
    if high_risk and "provider" not in roles and roles:
        treated_as_provider = [cid for field, cid in ART_25_BASIS if getattr(a, field)]
        if treated_as_provider:
            roles.append("provider")

    transparency: list[str] = []
    if a.interacts_with_persons:
        transparency.append("art_50.par_1")
    if a.generates_synthetic_content:
        transparency.append("art_50.par_2")
    if a.deploys_emotion_or_biometric_categorisation:
        transparency.append("art_50.par_3")
    if a.deploys_deep_fakes:
        transparency.append("art_50.par_4")

    gpai: list[str] = []
    if a.gpai_provider:
        gpai.append("art_53")
        if a.gpai_non_eu:
            gpai.append("art_54")
        if a.gpai_systemic:
            gpai.append("art_55")

    # Article 2(12): free and open-source systems are outside the Regulation
    # unless they are high-risk, fall under Article 5, or under Article 50.
    open_source_exempt = a.open_source and not (prohibited or high_risk or transparency)

    in_scope = a.is_ai_system and not scope_exclusions and not open_source_exempt

    if not in_scope:
        headline = "OUT_OF_SCOPE"
    elif prohibited:
        headline = "PROHIBITED_FLAG"
    elif high_risk:
        headline = "HIGH_RISK"
    elif a.product_safety_component:
        headline = "HIGH_RISK_POSSIBLE"
    elif transparency:
        headline = "TRANSPARENCY"
    else:
        headline = "MINIMAL"

    return Decision(
        headline=headline,
        in_scope=in_scope,
        scope_exclusions=scope_exclusions,
        open_source_exempt=open_source_exempt,
        roles=roles,
        treated_as_provider_basis=treated_as_provider,
        prohibited_flags=prohibited,
        high_risk_basis=high_risk_basis,
        annex_iii_note=annex_note,
        product_route=a.product_safety_component,
        derogation_claimed=high_risk and a.relies_on_6_3,
        transparency=transparency,
        gpai=gpai,
    )
