"""POST /assess and GET /assess/questionnaire: the assessment wedge.

Deterministic and read-only. The questionnaire ships with the provision text
each question rests on; the report quotes provisions verbatim. No LLM, no
embeddings, no writes, no quota (nothing here costs money). Same service
token gate and per-minute limit as every other endpoint.
"""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import Caller, DbSession, ServiceToken
from app.assessment.questionnaire import Questionnaire, build_questionnaire
from app.assessment.report import _Corpus, build_report
from app.assessment.schema import Answers, AssessmentResult
from app.config import PER_MINUTE_LIMIT
from app.rate_limit import limiter

router = APIRouter(prefix="/assess")


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
