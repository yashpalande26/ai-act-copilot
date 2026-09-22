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
    get_owned_session,
    resolve_user,
)
from app.api.history import derive_title
from app.config import (
    MAX_OUTPUT_TOKENS,
    MAX_QUESTION_CHARS,
    PER_MINUTE_LIMIT,
    followup_rewrite_enabled,
)
from app.db.models import ChatSession, CorpusVersion
from app.generation.answer import (
    ABSTENTION_TEXT,
    RewriteInfo,
    generate_grounded_answer,
)
from app.generation.rewrite import load_history, rewrite_followup
from app.generation.scope import SCOPE_MESSAGE, is_trivial_input
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
    # None only for a scope notice: nothing was retrieved, no session was
    # created or touched, so there is no thread to carry forward.
    session_id: UUID | None
    # A greeting or empty input answered with the scope message before any
    # embedding or model call. Deterministic, free, not a retrieval refusal.
    scope_notice: bool = False
    # Turn 2+ only: the standalone question the answer was retrieved for,
    # when the follow-up was rewritten. None on a first turn or a pass-through.
    rewritten_query: str | None = None


def _get_or_create_session(
    session: Session,
    user_id: UUID,
    corpus_version_id: int,
    session_id: UUID | None,
    question: str,
) -> ChatSession:
    if session_id is not None:
        # Ownership check: without it a caller could append to - and read the
        # history of - another user's conversation. Shared with the history
        # endpoints (deps.get_owned_session) so the rule exists once.
        return get_owned_session(session, user_id, session_id)

    # The title is the first question, trimmed to a sidebar-sized line. Set
    # once here; older sessions without one get the same derivation at read
    # time in history.py, so no backfill is needed.
    chat = ChatSession(
        user_id=user_id,
        corpus_version_id=corpus_version_id,
        title=derive_title(question),
    )
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
    if is_trivial_input(payload.question):
        # "hey", "thanks", "???": say what the copilot is for instead of
        # spending a call to retrieve nothing. No quota, no session, no trace.
        return AskResponse(
            answer=SCOPE_MESSAGE,
            citations=[],
            abstained=True,
            session_id=None,
            scope_notice=True,
        )
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
        session, user.id, corpus_version.id, payload.session_id, payload.question
    )

    # Follow-up rewriting, turn 2+ only: an existing session with prior
    # messages. The rewrite yields the query retrieval runs on; the user's own
    # text is what gets stored. Grounding, citations and refusal are decided
    # downstream exactly as for a first turn. Gated OFF by default: see
    # config.followup_rewrite_enabled (value gate not met on 22 Sep 2026).
    history = (
        load_history(session, chat.id)
        if payload.session_id is not None and followup_rewrite_enabled()
        else []
    )
    rewrite = rewrite_followup(history, payload.question)

    result = generate_grounded_answer(
        session,
        rewrite.query,
        corpus_version.id,
        chat.id,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        user_text=payload.question,
        rewrite=RewriteInfo(
            applied=rewrite.applied,
            prompt_tokens=rewrite.prompt_tokens,
            completion_tokens=rewrite.completion_tokens,
        ),
    )

    return AskResponse(
        rewritten_query=rewrite.query if rewrite.applied else None,
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
