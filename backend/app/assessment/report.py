"""Turn a Decision into the dated report: verbatim provisions, labels, dates,
penalty ceilings. The only database access in the package, and it is
read-only: provisions are loaded by citation_id, never retrieved by similarity.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment import penalties
from app.assessment.engine import assess
from app.assessment.obligations import GroupSpec, plan_obligations
from app.assessment.schema import (
    Answers,
    AssessmentResult,
    Decision,
    Flag,
    ObligationGroup,
    Penalties,
    PenaltyLine,
    ProvisionText,
)
from app.db.models import CorpusVersion, Provision
from app.ingestion.chunker import citation_label

ROLE_DEFINITIONS = {
    "provider": "art_3.pt_3",
    "deployer": "art_3.pt_4",
    "authorised_representative": "art_3.pt_5",
    "importer": "art_3.pt_6",
    "distributor": "art_3.pt_7",
}

HEADLINES = {
    "OUT_OF_SCOPE": "Based on your answers, the Regulation appears not to apply to this system.",
    "PROHIBITED_FLAG": (
        "Based on your answers, this system appears to match the pattern of a "
        "prohibited practice under Article 5(1). This is a legal red flag, not a "
        "determination; seek counsel."
    ),
    "HIGH_RISK": "Based on your answers, this system appears to be high-risk under Article 6(2).",
    "HIGH_RISK_POSSIBLE": (
        "Based on your answers, this system may be high-risk under Article 6(1). "
        "Annex I is not in this tool's corpus, so it cannot confirm which Union "
        "harmonisation legislation applies."
    ),
    "TRANSPARENCY": (
        "Based on your answers, this system does not appear to be high-risk, "
        "but transparency obligations under Article 50 appear to apply."
    ),
    "MINIMAL": (
        "Based on your answers, this system does not appear to fall within the "
        "prohibited, high-risk or transparency categories."
    ),
}

STANDING_COMMENTARY = (
    (
        "This report is informational and is not legal advice. It restates your "
        "answers against the quoted text of the Regulation; it does not certify "
        "compliance and cannot replace counsel."
    ),
    (
        "Every quoted provision is taken verbatim from the consolidated text named "
        "below. Sentences in the tool's own words are labelled as commentary."
    ),
)


class _Corpus:
    """All provisions of one corpus version, indexed once per request."""

    def __init__(self, session: Session):
        self.version = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        if self.version is None:
            raise LookupError("no corpus_version")
        rows = (
            session.execute(
                select(Provision)
                .where(Provision.corpus_version_id == self.version.id)
                .order_by(Provision.id)  # document order
            )
            .scalars()
            .all()
        )
        self.by_id = {r.citation_id: r for r in rows}
        self.children: dict[str, list[str]] = {}
        for r in rows:
            parent = r.citation_id.rsplit(".", 1)[0] if "." in r.citation_id else None
            if parent:
                self.children.setdefault(parent, []).append(r.citation_id)

    def text(self, cid: str) -> str:
        row = self.by_id[cid]
        return " ".join((row.text_content or "").split())

    def node(self, cid: str, mode: str = "full") -> ProvisionText:
        if cid not in self.by_id:
            raise LookupError(f"citation_id {cid!r} is not in corpus {self.version.id}")
        kids: list[ProvisionText] = []
        if mode == "full":
            kids = [self.node(c, "full") for c in self.children.get(cid, [])]
        elif mode == "heading_par1":
            first = next(
                (c for c in self.children.get(cid, []) if c.endswith(".par_1")), None
            )
            if first:
                kids = [self.node(first, "full")]
        return ProvisionText(
            citation_id=cid,
            citation_label=citation_label(cid),
            text=self.text(cid),
            children=kids,
        )


def _group(corpus: _Corpus, spec: GroupSpec) -> ObligationGroup:
    return ObligationGroup(
        key=spec.key,
        title=spec.title,
        role=spec.role,
        provisions=[corpus.node(cid, spec.mode) for cid in spec.ids],
        applies_from=corpus.node(spec.applies_from, "self")
        if spec.applies_from
        else None,
        commentary=spec.commentary,
    )


def _penalties(corpus: _Corpus, a: Answers, d: Decision) -> Penalties:
    obligations_flagged = bool(
        d.in_scope and (d.high_risk_basis or d.transparency or d.gpai)
    )
    status = penalties.turnover_status(
        undertaking=a.undertaking, turnover_eur=a.turnover_eur
    )
    lines = penalties.compute(
        par3_text=corpus.text("art_99.par_3"),
        par4_text=corpus.text("art_99.par_4"),
        par5_text=corpus.text("art_99.par_5"),
        art5_flagged=bool(d.prohibited_flags),
        obligations_flagged=obligations_flagged,
        undertaking=a.undertaking,
        turnover_eur=a.turnover_eur,
        sme_or_startup=a.sme_or_startup,
        smc=a.smc,
    )
    return Penalties(
        lines=[
            PenaltyLine(
                paragraph=corpus.node(c.paragraph_id, "full"),
                applicable=c.applicable,
                eur_cap=c.eur_cap,
                pct_cap=c.pct_cap,
                rule=c.rule,  # type: ignore[arg-type]
                rule_basis=[corpus.node(b, "self") for b in c.rule_basis],
                ceiling_eur=c.ceiling_eur,
                why=c.why,
            )
            for c in lines
        ],
        factors=corpus.node("art_99.par_7", "full"),
        commentary=(
            "These are the maximum administrative fine ceilings the Regulation "
            "allows for the relevant paragraph, computed from the quoted text and "
            "the turnover you entered. They are not an estimate of any fine; "
            "Article 99(7) lists what authorities weigh in each case."
            if status in ("provided", "not_needed")
            else "These are the maximum administrative fine ceilings the Regulation "
            "allows for the relevant paragraph, quoted from the text. No positive "
            "annual turnover was entered, so the percentage limb is not computed "
            "for you. They are not an estimate of any fine; Article 99(7) lists "
            "what authorities weigh in each case."
        ),
        turnover_status=status,
    )


def build_report(session: Session, a: Answers) -> AssessmentResult:
    corpus = _Corpus(session)
    d = assess(a)
    plan = plan_obligations(
        d,
        fria_body=a.fria_body,
        acts_for_public_authority=a.acts_for_public_authority,
        generates_synthetic_content=a.generates_synthetic_content,
    )

    commentary = list(STANDING_COMMENTARY)
    if d.annex_iii_note:
        commentary.append(d.annex_iii_note)
    if d.open_source_exempt:
        commentary.append(
            "You indicated a free and open-source licence. Article 2(12) places "
            "such systems outside the Regulation unless they are high-risk, fall "
            "under Article 5, or under Article 50; none of those matched your answers."
        )
    if d.product_route:
        commentary.append(
            "Article 6(1) turns on Annex I, which this tool's corpus does not yet "
            "contain. Treat the product-route result as incomplete and check the "
            "product legislation that applies to you."
        )
    if d.treated_as_provider_basis:
        commentary.append(
            "Whether a change is a 'substantial modification' (Article 3(23)) is a "
            "legal characterisation; this tool recorded your answer and did not decide it."
        )

    derogation: list[ProvisionText] = []
    if d.high_risk_basis:
        derogation.append(corpus.node("art_6.par_3", "full"))
        if d.derogation_claimed:
            derogation.append(corpus.node("art_6.par_4", "self"))

    return AssessmentResult(
        generated_at=datetime.now(UTC),
        corpus_version_id=corpus.version.id,
        corpus_consolidated_date=str(corpus.version.consolidated_date),
        decision=d,
        headline_text=HEADLINES[d.headline],
        scope=[corpus.node(c, "self") for c in d.scope_exclusions]
        + ([corpus.node("art_2.par_12", "self")] if d.open_source_exempt else []),
        role_definitions=[corpus.node(ROLE_DEFINITIONS[r], "self") for r in d.roles],
        treated_as_provider=[
            corpus.node(c, "self") for c in d.treated_as_provider_basis
        ],
        prohibited_flags=[
            Flag(key=c.rsplit("_", 1)[-1], provision=corpus.node(c, "full"))
            for c in d.prohibited_flags
        ],
        high_risk_basis=corpus.node(d.high_risk_basis, "self")
        if d.high_risk_basis
        else None,
        derogation=derogation,
        product_route=(
            [
                corpus.node("art_6.par_1", "full"),
                corpus.node("art_6.par_1a", "self"),
                corpus.node("art_6.par_1b", "self"),
            ]
            if d.product_route
            else []
        ),
        obligations=[_group(corpus, spec) for spec in plan.groups],
        dates=[corpus.node(c, "self") for c in plan.dates],
        penalties=_penalties(corpus, a, d),
        commentary=commentary,
    )
