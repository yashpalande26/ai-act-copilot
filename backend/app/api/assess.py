"""POST /assess, GET /assess/questionnaire, POST /assess/extract.

/assess and /questionnaire are deterministic and read-only: no LLM, no
writes, no quota. /extract is the ONE paid call in the assessment path: prose
in, structured answers plus provenance out. It never runs the engine and
never returns a verdict; the user confirms the answers and then calls
/assess like anyone else. Gated like chat: service token, per-minute limit,
per-environment daily quota (extraction_run rows count with query_trace).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import (
    Caller,
    DbSession,
    ServiceToken,
    enforce_daily_quota,
    resolve_user,
)
from app.assessment.questionnaire import Questionnaire, build_questionnaire
from app.assessment.report import _Corpus, build_report
from app.assessment.schema import Answers, AssessmentResult
from app.config import MAX_DESCRIPTION_CHARS, PER_MINUTE_LIMIT, app_env
from app.db.models import ExtractionRun
from app.extraction.extraction import (
    ExtractedAnswers,
    build_system_prompt,
    prompt_version,
    to_answers,
)
from app.extraction.llm import get_extractor
from app.rate_limit import limiter

router = APIRouter(prefix="/assess")

EXTRACTION_NOTE = (
    "Pre-filled from your description as a head start. Nothing has been "
    "assessed yet: answer every question marked to confirm and check the rest "
    "before building the report."
)


class ExtractRequest(BaseModel):
    # Length-capped by Pydantic BEFORE any spend, like MAX_QUESTION_CHARS on /ask.
    description: str = Field(min_length=20, max_length=MAX_DESCRIPTION_CHARS)


class Extracted(BaseModel):
    """Answers and where they came from. Deliberately no headline, no report:
    the verdict is the engine's, after the user has confirmed."""

    id: UUID
    created_at: datetime
    model: str
    prompt_version: str
    answers: Answers
    provenance: dict[str, Literal["inferred", "unknown"]]
    quotes: dict[str, str]  # field -> the verbatim passage that justified it
    to_confirm: list[str]  # fields left unknown; the UI blocks the engine on these
    note: str


@router.post("/extract", response_model=Extracted, status_code=status.HTTP_201_CREATED)
@limiter.limit(PER_MINUTE_LIMIT)
def extract_answers(
    request: Request,  # required by slowapi to key the limiter
    body: ExtractRequest,
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> Extracted:
    user = resolve_user(session, caller)
    enforce_daily_quota(session, user)
    try:
        corpus = _Corpus(session)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="corpus_unavailable"
        ) from exc
    prompt = build_system_prompt(lambda cid: corpus.node(cid, "self"))
    extractor = get_extractor()
    description = body.description.strip()

    # The quota record. Written whatever happens next (fail-closed: if this
    # row cannot be stored the request fails), so a call can never go uncounted.
    row = ExtractionRun(
        user_id=user.id,
        corpus_version_id=corpus.version.id,
        environment=app_env(),
        model=extractor.name,
        prompt_version=prompt_version(prompt),
        status="failed",
        input_chars=len(description),
        latency_ms=0,
        description=description,
    )
    try:
        out = extractor.extract(
            system_prompt=prompt, user_text=description, schema=ExtractedAnswers
        )
    except Exception as exc:
        session.add(row)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="extraction_unavailable",
        ) from exc

    row.prompt_tokens = out.prompt_tokens
    row.completion_tokens = out.completion_tokens
    row.latency_ms = out.latency_ms
    if out.parsed is None:
        row.status = "refused"
        session.add(row)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="extraction_refused",
        )

    mapped = to_answers(out.parsed, description)
    row.status = "ok"
    row.extracted = out.parsed.model_dump(mode="json")
    row.provenance = dict(mapped.provenance)
    session.add(row)
    session.commit()
    session.refresh(row)
    return Extracted(
        id=row.id,
        created_at=row.created_at,
        model=row.model,
        prompt_version=row.prompt_version,
        answers=mapped.answers,
        provenance=mapped.provenance,
        quotes=mapped.quotes,
        to_confirm=[f for f, p in mapped.provenance.items() if p == "unknown"],
        note=EXTRACTION_NOTE,
    )


@router.get("/questionnaire", response_model=Questionnaire)
@limiter.limit(PER_MINUTE_LIMIT)
def questionnaire(
    request: Request,  # required by slowapi to key the limiter
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> Questionnaire:
    try:
        corpus = _Corpus(session)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="corpus_unavailable"
        ) from exc
    return build_questionnaire(
        lambda cid: corpus.node(cid, "self"),
        corpus.version.id,
        str(corpus.version.consolidated_date),
    )


@router.post("", response_model=AssessmentResult)
@limiter.limit(PER_MINUTE_LIMIT)
def assess_system(
    request: Request,  # required by slowapi to key the limiter
    answers: Answers,
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> AssessmentResult:
    try:
        return build_report(session, answers)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="corpus_unavailable"
        ) from exc
