"""Which provisions apply, given a Decision. Data, reviewed row by row.

This table answers "which provisions apply for this tier and role". The ADR-10
actor map answers a different question ("whose obligation is this provision")
and is used by the tests as a consistency check on these rows, never as the
source of them. Every id here is quoted verbatim in the report and every id
must exist in the corpus (tests enforce both).

`mode`:  "full"          the article heading and every descendant
         "heading_par1"  the heading and paragraph 1 only (Section 2
                         requirements, listed as what the system must meet)
         "self"          just the cited provision
"""

from dataclasses import dataclass, field

from app.assessment.schema import Decision


@dataclass(frozen=True)
class GroupSpec:
    key: str
    title: str
    role: str
    ids: tuple[str, ...]
    mode: str = "full"
    applies_from: str | None = None
    commentary: str | None = None


# --- high-risk, provider ---------------------------------------------------
PROVIDER_HIGH_RISK = (
    GroupSpec(
        "provider_core",
        "Obligations of providers of high-risk AI systems",
        "provider",
        ("art_16",),
        applies_from="art_113.pt_c",
    ),
    GroupSpec(
        "provider_requirements",
        "Requirements the high-risk system must meet (Section 2)",
        "provider",
        ("art_8", "art_9", "art_10", "art_11", "art_12", "art_13", "art_14", "art_15"),
        mode="heading_par1",
        applies_from="art_113.pt_c",
        commentary=(
            "Article 16, point (a) makes the provider responsible for compliance "
            "with these requirements; each article is shown with its first "
            "paragraph only."
        ),
    ),
    GroupSpec(
        "provider_management",
        "Quality management, documentation, logs, corrective action, cooperation",
        "provider",
        ("art_17", "art_18", "art_19", "art_20", "art_21"),
        applies_from="art_113.pt_c",
    ),
    GroupSpec(
        "provider_conformity",
        "Conformity assessment, declaration of conformity, CE marking, registration",
        "provider",
        ("art_43", "art_47", "art_48", "art_49.par_1"),
        applies_from="art_113.pt_c",
    ),
    GroupSpec(
        "provider_post_market",
        "Post-market monitoring and serious-incident reporting",
        "provider",
        ("art_72", "art_73.par_1"),
        applies_from="art_113.pt_c",
    ),
)
PROVIDER_DEROGATION = GroupSpec(
    "provider_derogation",
    "If you rely on the Article 6(3) derogation",
    "provider",
    ("art_6.par_4", "art_49.par_2"),
    mode="self",
    commentary=(
        "You indicated you intend to rely on Article 6(3). This tool has not "
        "applied the derogation; the assessment remains high-risk unless the "
        "derogation is documented as Article 6(4) requires."
    ),
)
PROVIDER_ART_25 = GroupSpec(
    "provider_art_25",
    "Why you are treated as the provider",
    "provider",
    ("art_25.par_1",),
    commentary="Based on your answers, Article 25(1) treats you as the provider.",
)

# --- high-risk, other operators ----------------------------------------------
DEPLOYER_HIGH_RISK = GroupSpec(
    "deployer_core",
    "Obligations of deployers of high-risk AI systems",
    "deployer",
    ("art_26",),
    applies_from="art_113.pt_c",
)
DEPLOYER_FRIA = GroupSpec(
    "deployer_fria",
    "Fundamental rights impact assessment",
    "deployer",
    ("art_27",),
    applies_from="art_113.pt_c",
    commentary=(
        "Shown because you indicated you are a body governed by public law, a "
        "private entity providing public services, or a deployer of an Annex "
        "III point 5(b) or (c) system."
    ),
)
DEPLOYER_REGISTRATION = GroupSpec(
    "deployer_registration",
    "Registration by public-authority deployers",
    "deployer",
    ("art_49.par_3",),
    mode="self",
    applies_from="art_113.pt_c",
)
DEPLOYER_EXPLANATION = GroupSpec(
    "deployer_explanation",
    "Right to explanation of individual decision-making",
    "deployer",
    ("art_86.par_1",),
    mode="self",
    applies_from="art_113.pt_c",
)
IMPORTER = GroupSpec(
    "importer",
    "Obligations of importers",
    "importer",
    ("art_23",),
    applies_from="art_113.pt_c",
)
DISTRIBUTOR = GroupSpec(
    "distributor",
    "Obligations of distributors",
    "distributor",
    ("art_24",),
    applies_from="art_113.pt_c",
)
AUTHORISED_REP = GroupSpec(
    "authorised_representative",
    "Authorised representatives of providers of high-risk AI systems",
    "authorised_representative",
    ("art_22",),
    applies_from="art_113.pt_c",
)

# --- everyone ----------------------------------------------------------------
AI_LITERACY = GroupSpec(
    "ai_literacy", "AI literacy", "all", ("art_4.par_1",), mode="self"
)
VOLUNTARY = GroupSpec(
    "voluntary",
    "Voluntary codes of conduct",
    "voluntary",
    ("art_95.par_1",),
    mode="self",
    commentary=(
        "No high-risk or transparency category matched your answers. Article "
        "95 codes of conduct are voluntary."
    ),
)

# --- transparency (Article 50) ----------------------------------------------
TRANSPARENCY_ROLE = {
    "art_50.par_1": "provider",
    "art_50.par_2": "provider",
    "art_50.par_3": "deployer",
    "art_50.par_4": "deployer",
}
TRANSPARENCY_COMMENTARY = (
    "Article 50 sits in Chapter IV, which applies from the Regulation's general "
    "application date of 2 August 2026. That date is a free-standing sentence "
    "of Article 113 that this corpus does not capture as a quotable provision, "
    "so it is stated here as commentary."
)

# --- general-purpose AI models -----------------------------------------------
GPAI_TITLES = {
    "art_53": "Obligations for providers of general-purpose AI models",
    "art_54": "Authorised representatives of providers of general-purpose AI models",
    "art_55": "Providers of general-purpose AI models with systemic risk",
}

ALL_SPECS: tuple[GroupSpec, ...] = (
    *PROVIDER_HIGH_RISK,
    PROVIDER_DEROGATION,
    PROVIDER_ART_25,
    DEPLOYER_HIGH_RISK,
    DEPLOYER_FRIA,
    DEPLOYER_REGISTRATION,
    DEPLOYER_EXPLANATION,
    IMPORTER,
    DISTRIBUTOR,
    AUTHORISED_REP,
    AI_LITERACY,
    VOLUNTARY,
)


@dataclass
class ObligationPlan:
    groups: list[GroupSpec] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)  # art_113 / art_111 ids


def plan_obligations(
    d: Decision,
    *,
    fria_body: bool,
    acts_for_public_authority: bool,
    generates_synthetic_content: bool,
) -> ObligationPlan:
    plan = ObligationPlan()
    if not d.in_scope:
        return plan

    plan.groups.append(AI_LITERACY)

    if d.high_risk_basis:
        plan.dates.append("art_113.pt_c")
        if "provider" in d.roles:
            if d.treated_as_provider_basis:
                plan.groups.append(PROVIDER_ART_25)
            plan.groups.extend(PROVIDER_HIGH_RISK)
            if d.derogation_claimed:
                plan.groups.append(PROVIDER_DEROGATION)
        if "deployer" in d.roles:
            plan.groups.append(DEPLOYER_HIGH_RISK)
            if fria_body:
                plan.groups.append(DEPLOYER_FRIA)
            if acts_for_public_authority:
                plan.groups.append(DEPLOYER_REGISTRATION)
            plan.groups.append(DEPLOYER_EXPLANATION)
        if "importer" in d.roles:
            plan.groups.append(IMPORTER)
        if "distributor" in d.roles:
            plan.groups.append(DISTRIBUTOR)
        if "authorised_representative" in d.roles:
            plan.groups.append(AUTHORISED_REP)

    for cid in d.transparency:
        plan.groups.append(
            GroupSpec(
                f"transparency_{cid.rsplit('_', 1)[-1]}",
                f"Transparency obligation ({TRANSPARENCY_ROLE[cid]} duty)",
                TRANSPARENCY_ROLE[cid],
                (cid, "art_50.par_5"),
                mode="self",
                commentary=TRANSPARENCY_COMMENTARY,
            )
        )
    if generates_synthetic_content and "art_50.par_2" in d.transparency:
        plan.dates.append("art_111.par_4")

    for cid in d.gpai:
        plan.groups.append(
            GroupSpec(
                f"gpai_{cid}",
                GPAI_TITLES[cid],
                "provider",
                (cid,),
                applies_from="art_113.pt_b",
            )
        )
    if d.gpai:
        plan.dates.append("art_113.pt_b")

    if d.prohibited_flags:
        plan.dates.append("art_113.pt_a")

    if d.headline == "MINIMAL":
        plan.groups.append(VOLUNTARY)

    # de-duplicate dates, keep order
    plan.dates = list(dict.fromkeys(plan.dates))
    return plan


def all_referenced_ids() -> set[str]:
    """Every citation id this module can emit; tests check each exists."""
    ids: set[str] = set()
    for spec in ALL_SPECS:
        ids.update(spec.ids)
        if spec.applies_from:
            ids.add(spec.applies_from)
    ids.update(TRANSPARENCY_ROLE)
    ids.update(GPAI_TITLES)
    ids.update({"art_50.par_5", "art_111.par_4", "art_113.pt_a", "art_113.pt_b"})
    return ids
