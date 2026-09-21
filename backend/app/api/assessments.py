"""Saved assessments: POST /assessments, GET /assessments, GET /assessments/{id}.

POST takes ANSWERS ONLY. The server re-runs the deterministic engine and the
report builder, then stores the answers with the decision they produced. A
client can therefore never save a headline, an obligation list or a penalty
figure it did not earn from its own answers.

Reads are ownership-scoped (WHERE user_id = the caller) and a foreign or
unknown id is a 404, never a 403. Reopening re-renders the report from the
stored answers against the CURRENT corpus: a saved row is not an immutable
snapshot of the quoted text (known limitation, recorded, not built).

No LLM, no embeddings, no quota: nothing here costs money.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    Caller,
    DbSession,
    ServiceToken,
    get_owned_assessment,
    get_owned_extraction,
    resolve_user,
)
from app.assessment.export import render_export
from app.assessment.report import build_report
from app.assessment.schema import Answers, AssessmentResult
from app.assessment.version import ENGINE_VERSION
from app.config import PER_MINUTE_LIMIT, app_env
from app.db.models import Assessment, ExtractionRun
from app.rate_limit import limiter

router = APIRouter(prefix="/assessments")

KNOWN_LIMITATION = (
    "Provision text is rendered from the current corpus when an assessment is "
    "reopened; a saved assessment is not an immutable snapshot of the quoted text."
)


def _prefilled_at(session: Session, row: Assessment) -> datetime | None:
    """When the answers started from a free-text extraction, its timestamp."""
    if row.extraction_run_id is None:
        return None
    run = session.get(ExtractionRun, row.extraction_run_id)
    return run.created_at if run is not None else None


class SavedSummary(BaseModel):
    id: UUID
    created_at: datetime
    headline: str
    roles: list[str]
    engine_version: str
    corpus_consolidated_date: str
    environment: str
    high_risk_basis: str | None
    source: str  # "form" | "extracted"


class SavedList(BaseModel):
    assessments: list[SavedSummary]


class Saved(BaseModel):
    id: UUID
    created_at: datetime
    engine_version: str
    corpus_consolidated_date: str
    environment: str
    source: str  # "form" | "extracted" (pre-filled from a description, then confirmed)
    extraction_id: UUID | None
    answers: Answers
    report: AssessmentResult
    known_limitation: str = KNOWN_LIMITATION


def _summary(row: Assessment) -> SavedSummary:
    return SavedSummary(
        id=row.id,
        created_at=row.created_at,
        headline=row.headline,
        roles=list(row.roles),
        engine_version=row.engine_version,
        corpus_consolidated_date=row.corpus_consolidated_date,
        environment=row.environment,
        high_risk_basis=(row.answers or {}).get("annex_iii_point") or None,
        source=row.source,
    )


@router.post("", response_model=Saved, status_code=status.HTTP_201_CREATED)
@limiter.limit(PER_MINUTE_LIMIT)
def save_assessment(
    request: Request,  # required by slowapi to key the limiter
    answers: Answers,
    extraction_id: UUID | None = None,
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> Saved:
    """`extraction_id` (query) links the record to the free-text extraction
    the answers started from. Owner-scoped: someone else's or an unknown id
    is a 404 and nothing is saved. The answers stored are the ones POSTED,
    i.e. what the user confirmed and possibly edited, never the raw output."""
    user = resolve_user(session, caller)
    extraction = (
        get_owned_extraction(session, user.id, extraction_id)
        if extraction_id is not None
        else None
    )
    try:
        report = build_report(session, answers)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="corpus_unavailable"
        ) from exc

    row = Assessment(
        user_id=user.id,
        corpus_version_id=report.corpus_version_id,
        environment=app_env(),
        engine_version=ENGINE_VERSION,
        corpus_consolidated_date=report.corpus_consolidated_date,
        answers=answers.model_dump(mode="json"),
        headline=report.decision.headline,
        roles=list(report.decision.roles),
        obligation_citation_ids=[
            p.citation_id for g in report.obligations for p in g.provisions
        ],
        penalties=report.penalties.model_dump(mode="json"),
        source="extracted" if extraction is not None else "form",
        extraction_run_id=extraction.id if extraction is not None else None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return Saved(
        id=row.id,
        created_at=row.created_at,
        engine_version=row.engine_version,
        corpus_consolidated_date=row.corpus_consolidated_date,
        environment=row.environment,
        source=row.source,
        extraction_id=row.extraction_run_id,
        answers=answers,
        report=report,
    )


@router.get("", response_model=SavedList)
@limiter.limit(PER_MINUTE_LIMIT)
def list_assessments(
    request: Request,  # required by slowapi to key the limiter
    limit: int = Query(default=50, ge=1, le=200),
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> SavedList:
    user = resolve_user(session, caller)
    rows = (
        session.execute(
            select(Assessment)
            .where(Assessment.user_id == user.id)  # ownership is the WHERE clause
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return SavedList(assessments=[_summary(r) for r in rows])


@router.get("/{assessment_id}/export.html", response_class=HTMLResponse)
@limiter.limit(PER_MINUTE_LIMIT)
def export_assessment(
    request: Request,  # required by slowapi to key the limiter
    assessment_id: UUID,
    download: bool = False,
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> HTMLResponse:
    """The self-contained HTML record. Same ownership rule as the JSON route
    (foreign or unknown id -> 404). `download=1` sets an attachment
    disposition; otherwise the document opens in the tab."""
    user = resolve_user(session, caller)
    row = get_owned_assessment(session, user.id, assessment_id)
    try:
        report = build_report(session, Answers.model_validate(row.answers))
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="corpus_unavailable"
        ) from exc
    html = render_export(
        report,
        assessment_id=str(row.id),
        saved_at=row.created_at,
        engine_version=row.engine_version,
        environment=row.environment,
        prefilled_at=_prefilled_at(session, row),
    )
    filename = f"ai-act-assessment-{str(row.id)[:8]}-{row.created_at:%Y-%m-%d}.html"
    disposition = "attachment" if download else "inline"
    return HTMLResponse(
        html,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{assessment_id}", response_model=Saved)
@limiter.limit(PER_MINUTE_LIMIT)
def get_assessment(
    request: Request,  # required by slowapi to key the limiter
    assessment_id: UUID,
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> Saved:
    user = resolve_user(session, caller)
    row = get_owned_assessment(session, user.id, assessment_id)
    answers = Answers.model_validate(row.answers)
    try:
        report = build_report(session, answers)  # live text, see KNOWN_LIMITATION
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="corpus_unavailable"
        ) from exc
    return Saved(
        id=row.id,
        created_at=row.created_at,
        engine_version=row.engine_version,
        corpus_consolidated_date=row.corpus_consolidated_date,
        environment=row.environment,
        source=row.source,
        extraction_id=row.extraction_run_id,
        answers=answers,
        report=report,
    )
