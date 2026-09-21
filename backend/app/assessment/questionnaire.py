"""The questionnaire as data. Each question names the provision it rests on;
the API attaches that provision's verbatim text so the frontend never carries
legal wording of its own. Labels and help are the tool's words (commentary).
"""

from pydantic import BaseModel

from app.assessment.engine import ANNEX_III_POINTS
from app.assessment.schema import PROHIBITED_KEYS, ProvisionText


class Option(BaseModel):
    value: str
    label: str
    basis: ProvisionText | None = None


class ShowIf(BaseModel):
    field: str
    equals: object  # a value, or for list fields any of these values
    any_of: list[str] | None = None


class Question(BaseModel):
    id: str  # matches an Answers field
    kind: str  # boolean | select | multiselect | number
    label: str
    help: str | None = None
    basis: list[ProvisionText] = []
    options: list[Option] = []
    show_if: ShowIf | None = None


class Step(BaseModel):
    key: str
    title: str
    intro: str | None = None
    questions: list[Question]


class Questionnaire(BaseModel):
    corpus_version_id: int
    corpus_consolidated_date: str
    steps: list[Step]


# (id, kind, label, help, basis ids)
_RAW: list[tuple[str, str, list[tuple]]] = [
    (
        "scope",
        "Scope",
        [
            (
                "is_ai_system",
                "boolean",
                "Is this an AI system as the Regulation defines it?",
                "Self-declared. The definition is quoted; this tool does not decide it.",
                ["art_3.pt_1"],
            ),
            (
                "personal_non_professional",
                "boolean",
                "Is it used only in a personal, non-professional capacity?",
                None,
                ["art_2.par_10"],
            ),
            (
                "research_only",
                "boolean",
                "Was it developed and put into service solely for scientific research and development?",
                None,
                ["art_2.par_6"],
            ),
            (
                "pre_market_only",
                "boolean",
                "Is it still only in research, testing or development, before being placed on the market or put into service?",
                None,
                ["art_2.par_8"],
            ),
            (
                "national_security_only",
                "boolean",
                "Is it used exclusively for military, defence or national security purposes?",
                None,
                ["art_2.par_3"],
            ),
            (
                "open_source",
                "boolean",
                "Is it released under a free and open-source licence?",
                "The exemption falls away for prohibited, high-risk and Article 50 systems, so the rest of the questions still apply.",
                ["art_2.par_12"],
            ),
        ],
    ),
    (
        "role",
        "Your role",
        [
            (
                "roles",
                "multiselect",
                "Which of these describes you? Select all that apply.",
                None,
                [],
            ),
            (
                "puts_own_name",
                "boolean",
                "Do you put your own name or trademark on a high-risk system someone else built?",
                None,
                ["art_25.par_1.pt_a"],
            ),
            (
                "substantial_modification",
                "boolean",
                "Have you made a substantial modification to a high-risk system already on the market?",
                "Whether a change is 'substantial' is a legal characterisation; the definition is quoted and your answer is recorded, not decided.",
                ["art_25.par_1.pt_b", "art_3.pt_23"],
            ),
            (
                "changed_intended_purpose",
                "boolean",
                "Have you changed the intended purpose of a system so that it becomes high-risk?",
                None,
                ["art_25.par_1.pt_c"],
            ),
        ],
    ),
    (
        "prohibited",
        "Prohibited practices screen",
        [
            (
                "prohibited_patterns",
                "multiselect",
                "Does the system do any of the following? Select every pattern that matches.",
                "A match is a red flag to take to counsel, not a determination. Each point carries conditions and exceptions; read the quoted text.",
                ["art_5.par_1"],
            ),
        ],
    ),
    (
        "high_risk",
        "High-risk classification",
        [
            (
                "product_safety_component",
                "boolean",
                "Is the system a safety component of a product, or itself a product, covered by EU product legislation that requires third-party conformity assessment?",
                "Annex I is not in this tool's corpus, so a 'yes' can only be reported as possibly high-risk.",
                ["art_6.par_1", "art_6.par_1a", "art_6.par_1b"],
            ),
            (
                "annex_iii_point",
                "select",
                "Does the system fall under one of the Annex III use cases? Pick the closest, or none.",
                None,
                ["art_6.par_2"],
            ),
            (
                "acts_for_public_authority",
                "boolean",
                "Are you a public authority, law-enforcement, competent or judicial authority, or acting on one's behalf?",
                "Some Annex III points apply only in that capacity.",
                [],
            ),
            (
                "biometric_verification_only",
                "boolean",
                "Is the sole purpose biometric verification (confirming a person is who they claim to be)?",
                None,
                ["anx_III.pt_1.sub_a"],
            ),
            (
                "fraud_detection_only",
                "boolean",
                "Is the system used for detecting financial fraud?",
                None,
                ["anx_III.pt_5.sub_b"],
            ),
            (
                "relies_on_6_3",
                "boolean",
                "Do you intend to rely on the Article 6(3) derogation?",
                "This tool never applies the derogation itself. Saying yes adds the documentation and registration duties to the report.",
                ["art_6.par_3", "art_6.par_4"],
            ),
            (
                "fria_body",
                "boolean",
                "Are you a body governed by public law, a private entity providing public services, or a deployer of an Annex III point 5(b) or 5(c) system?",
                None,
                ["art_27.par_1"],
            ),
        ],
    ),
    (
        "transparency",
        "Transparency",
        [
            (
                "interacts_with_persons",
                "boolean",
                "Does the system interact directly with natural persons?",
                None,
                ["art_50.par_1"],
            ),
            (
                "generates_synthetic_content",
                "boolean",
                "Does it generate synthetic audio, image, video or text content?",
                None,
                ["art_50.par_2"],
            ),
            (
                "deploys_emotion_or_biometric_categorisation",
                "boolean",
                "Do you deploy it for emotion recognition or biometric categorisation?",
                None,
                ["art_50.par_3"],
            ),
            (
                "deploys_deep_fakes",
                "boolean",
                "Do you deploy it to generate or manipulate content that constitutes a deep fake?",
                None,
                ["art_50.par_4"],
            ),
        ],
    ),
    (
        "gpai",
        "General-purpose AI models",
        [
            (
                "gpai_provider",
                "boolean",
                "Do you place a general-purpose AI model on the market?",
                None,
                ["art_3.pt_63"],
            ),
            (
                "gpai_non_eu",
                "boolean",
                "Are you established outside the Union?",
                None,
                ["art_54.par_1"],
            ),
            (
                "gpai_systemic",
                "boolean",
                "Does the model meet the systemic-risk conditions?",
                None,
                ["art_51.par_1", "art_51.par_2"],
            ),
        ],
    ),
    (
        "penalties",
        "Exposure inputs",
        [
            (
                "undertaking",
                "boolean",
                "Are you an undertaking (a business)?",
                None,
                ["art_99.par_3"],
            ),
            (
                "turnover_eur",
                "number",
                "Total worldwide annual turnover for the preceding financial year, in EUR",
                "Used only to compute the ceilings; not stored.",
                [],
            ),
            (
                "sme_or_startup",
                "boolean",
                "Are you an SME or a start-up?",
                "Self-declared. The SME definition comes from Recommendation 2003/361, which is not in this corpus.",
                ["art_99.par_6"],
            ),
            (
                "smc",
                "boolean",
                "Are you a small mid-cap (SMC)?",
                "Self-declared.",
                ["art_99.par_6a"],
            ),
        ],
    ),
]

_SHOW_IF = {
    "puts_own_name": ShowIf(
        field="roles", equals=None, any_of=["deployer", "importer", "distributor"]
    ),
    "substantial_modification": ShowIf(
        field="roles", equals=None, any_of=["deployer", "importer", "distributor"]
    ),
    "changed_intended_purpose": ShowIf(
        field="roles", equals=None, any_of=["deployer", "importer", "distributor"]
    ),
    "acts_for_public_authority": ShowIf(field="annex_iii_point", equals="__any__"),
    "biometric_verification_only": ShowIf(
        field="annex_iii_point", equals="anx_III.pt_1.sub_a"
    ),
    "fraud_detection_only": ShowIf(
        field="annex_iii_point", equals="anx_III.pt_5.sub_b"
    ),
    "relies_on_6_3": ShowIf(field="annex_iii_point", equals="__any__"),
    "fria_body": ShowIf(field="annex_iii_point", equals="__any__"),
    "gpai_non_eu": ShowIf(field="gpai_provider", equals=True),
    "gpai_systemic": ShowIf(field="gpai_provider", equals=True),
    "turnover_eur": ShowIf(field="undertaking", equals=True),
    "sme_or_startup": ShowIf(field="undertaking", equals=True),
    "smc": ShowIf(field="undertaking", equals=True),
}

ROLE_OPTIONS = [
    (
        "provider",
        "Provider: I develop it, or have it developed, and place it on the market or put it into service under my own name or trademark",
        "art_3.pt_3",
    ),
    (
        "deployer",
        "Deployer: I use it under my authority in a professional context",
        "art_3.pt_4",
    ),
    (
        "importer",
        "Importer: I am established in the EU and place on the market a system bearing a non-EU party's name",
        "art_3.pt_6",
    ),
    (
        "distributor",
        "Distributor: I make it available in the supply chain and am neither provider nor importer",
        "art_3.pt_7",
    ),
    (
        "authorised_representative",
        "Authorised representative: I hold a written mandate from a non-EU provider",
        "art_3.pt_5",
    ),
]


def build_questionnaire(
    node, corpus_version_id: int, consolidated: str
) -> Questionnaire:
    """`node(cid)` resolves a citation id to a ProvisionText (report._Corpus)."""
    steps: list[Step] = []
    for key, title, qs in _RAW:
        questions = []
        for qid, kind, label, help_, basis in qs:
            options: list[Option] = []
            if qid == "roles":
                options = [
                    Option(value=v, label=lbl, basis=node(b))
                    for v, lbl, b in ROLE_OPTIONS
                ]
            elif qid == "prohibited_patterns":
                options = [
                    Option(
                        value=k,
                        label=f"Article 5(1)({k})",
                        basis=node(f"art_5.par_1.pt_{k}"),
                    )
                    for k in PROHIBITED_KEYS
                ]
            elif qid == "annex_iii_point":
                options = [Option(value="", label="None of these", basis=None)] + [
                    Option(value=p, label=node(p).citation_label, basis=node(p))
                    for p in ANNEX_III_POINTS
                ]
            questions.append(
                Question(
                    id=qid,
                    kind=kind,
                    label=label,
                    help=help_,
                    basis=[node(b) for b in basis],
                    options=options,
                    show_if=_SHOW_IF.get(qid),
                )
            )
        steps.append(Step(key=key, title=title, questions=questions))
    return Questionnaire(
        corpus_version_id=corpus_version_id,
        corpus_consolidated_date=consolidated,
        steps=steps,
    )


def all_referenced_ids() -> set[str]:
    ids: set[str] = set()
    for _, _, qs in _RAW:
        for _, _, _, _, basis in qs:
            ids.update(basis)
    ids.update(b for _, _, b in ROLE_OPTIONS)
    ids.update(f"art_5.par_1.pt_{k}" for k in PROHIBITED_KEYS)
    ids.update(ANNEX_III_POINTS)
    return ids
