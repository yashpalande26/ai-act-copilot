"""POST /ask - the authenticated, cost-controlled grounded-answer endpoint.

Unlike /classify (pure CPU, free), every call here spends real money on
gpt-4o, so auth, rate limiting and cost ceilings are part of the endpoint's
definition rather than a later hardening pass.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    Caller,
    DbSession,
    ServiceToken,
    enforce_daily_quota,
    resolve_user,
)
from app.config import MAX_OUTPUT_TOKENS, MAX_QUESTION_CHARS, PER_MINUTE_LIMIT
from app.db.models import ChatSession, CorpusVersion
from app.generation.answer import ABSTENTION_TEXT, generate_grounded_answer
from app.rate_limit import limiter

router = APIRouter()


class AskRequest(BaseModel):
    # Enforced by Pydantic BEFORE the handler body runs, so an oversized
    # question costs nothing - no embedding call, no LLM call.
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    session_id: UUID | None = None


class AskCitation(BaseModel):
    citation_id: str
    citation_label: str
    quoted_text: str


class AskResponse(BaseModel):
    answer: str
    citations: list[AskCitation]
    abstained: bool
    session_id: UUID


def _get_or_create_session(
    session: Session, user_id: UUID, corpus_version_id: int, session_id: UUID | None
) -> ChatSession:
    if session_id is not None:
        chat = (
            session.execute(select(ChatSession).where(ChatSession.id == session_id))
            .scalars()
            .first()
        )
        # Ownership check: without it a caller could append to - and read the
        # history of - another user's conversation. 404 rather than 403 so we
        # don't confirm that someone else's session id exists.
        if chat is None or chat.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found"
            )
        return chat

    chat = ChatSession(user_id=user_id, corpus_version_id=corpus_version_id)
    session.add(chat)
    session.commit()
    return chat


@router.post("/ask", response_model=AskResponse)
@limiter.limit(PER_MINUTE_LIMIT)
def ask(
    request: Request,  # required by slowapi to key the limiter
    payload: AskRequest,
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> AskResponse:
    user = resolve_user(session, caller)
    enforce_daily_quota(session, user)

    corpus_version = (
        session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
        .scalars()
        .first()
    )
    if corpus_version is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="corpus_unavailable"
        )

    chat = _get_or_create_session(
        session, user.id, corpus_version.id, payload.session_id
    )

    result = generate_grounded_answer(
        session,
        payload.question,
        corpus_version.id,
        chat.id,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    return AskResponse(
        answer=result.answer,
        citations=[
            AskCitation(
                citation_id=c.citation_id,
                citation_label=c.citation_label,
                quoted_text=c.chunk_text,
            )
            for c in result.citations
        ],
        abstained=result.answer == ABSTENTION_TEXT,
        session_id=chat.id,
    )
