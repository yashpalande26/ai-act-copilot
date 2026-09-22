"""Operator-only trace viewer: GET /admin/traces and GET /admin/traces/{id}.

Reads query_trace and retrieval_trace exactly as _write_trace_safe wrote them,
joined to the user who asked (query_trace -> chat_session -> app_user).
Nothing here is derived from the live retriever; the one computed field,
`downweighted`, replays the actor prior's decision from two stored facts:
the query actor recorded in retrieval_config and the provision's own label
from the static actor map.

Access: deps.require_admin (service token, then the ADMIN_EMAILS allowlist,
else 404). Admin reads have NO user filter by design and see every user's
traces, including who asked; this is deliberately separate from the per-user
ownership model in history.py, and the two are never combined. No quota, no
OpenAI.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Admin, Caller, DbSession
from app.config import PER_MINUTE_LIMIT
from app.db.models import AppUser, Chunk, QueryTrace, RetrievalTrace
from app.ingestion.chunker import citation_label
from app.rate_limit import limiter
from app.retrieval.actor import actor_for

router = APIRouter(prefix="/admin")

PREVIEW_CHARS = 240


class RetrievalInfo(BaseModel):
    config: str  # "hybrid_bm25" or "vector_only_degraded"
    query_actor: str | None
    factor: float | None
    legacy: bool  # written before ADR-10: no actor information recorded


def parse_retrieval_config(raw: str) -> RetrievalInfo:
    """Three shapes exist in the live table and all must parse:
    "hybrid_bm25"                              -> legacy, no actor info
    "hybrid_bm25|actor=none"                   -> prior ran, did not fire
    "hybrid_bm25|actor=provider|factor=0.25"   -> prior fired
    (and the same suffixes on "vector_only_degraded")."""
    parts = raw.split("|")
    info = RetrievalInfo(config=parts[0], query_actor=None, factor=None, legacy=True)
    for part in parts[1:]:
        key, _, value = part.partition("=")
        if key == "actor":
            info.legacy = False
            info.query_actor = None if value == "none" else value
        elif key == "factor":
            try:
                info.factor = float(value)
            except ValueError:
                info.factor = None
    return info


class TraceSummary(BaseModel):
    id: UUID
    created_at: datetime
    environment: str
    user_id: UUID
    user_email: str
    question: str
    retrieval_config: str
    abstained: bool
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    retrieval_latency_ms: int
    generation_latency_ms: int | None


class TraceList(BaseModel):
    traces: list[TraceSummary]
    next_before: datetime | None


class TraceCitation(BaseModel):
    citation_id: str
    citation_label: str


class TraceCandidate(BaseModel):
    final_rank: int
    citation_id: str
    citation_label: str
    chunk_id: int | None
    chunk_preview: str | None
    vector_rank: int | None
    lexical_rank: int | None
    rrf_score: float | None
    similarity: float | None
    used_in_context: bool
    actor: str | None
    downweighted: bool


class TraceDetail(TraceSummary):
    rewritten_query: str | None = None  # turn 2+: the standalone query retrieval ran on
    retrieval: RetrievalInfo
    answer: str
    citations: list[TraceCitation]
    candidates: list[TraceCandidate]


def _summary(qt: QueryTrace, user_id: UUID, user_email: str) -> dict:
    return {
        "id": qt.id,
        "created_at": qt.created_at,
        "environment": qt.environment,
        "user_id": user_id,
        "user_email": user_email,
        "question": qt.query_text,
        "rewritten_query": qt.rewritten_query,
        "retrieval_config": qt.retrieval_config,
        "abstained": qt.abstained,
        "model": qt.model,
        "prompt_tokens": qt.prompt_tokens,
        "completion_tokens": qt.completion_tokens,
        "retrieval_latency_ms": qt.retrieval_latency_ms,
        "generation_latency_ms": qt.generation_latency_ms,
    }


def _traces_with_user():
    """query_trace joined to the user who asked. Direct, so traces whose chat
    was later deleted (chat_session_id NULL) stay visible to the operator."""
    return select(QueryTrace, AppUser.id, AppUser.email).join(
        AppUser, AppUser.id == QueryTrace.user_id
    )


@router.get("/traces", response_model=TraceList)
@limiter.limit(PER_MINUTE_LIMIT)
def list_traces(
    request: Request,  # required by slowapi to key the limiter
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = None,
    environment: str | None = None,
    user_email: str | None = None,
    caller: Caller = Admin,
    session: Session = DbSession,
) -> TraceList:
    # Keyset pagination on created_at: stable while new traces keep arriving,
    # which offset paging is not. `before` is the previous page's last row.
    stmt = _traces_with_user()
    if before is not None:
        stmt = stmt.where(QueryTrace.created_at < before)
    if environment is not None:
        stmt = stmt.where(QueryTrace.environment == environment)
    if user_email is not None:
        stmt = stmt.where(AppUser.email == user_email.strip().lower())
    rows = session.execute(
        stmt.order_by(QueryTrace.created_at.desc(), QueryTrace.id.desc()).limit(
            limit + 1
        )
    ).all()
    more = len(rows) > limit
    page = rows[:limit]
    return TraceList(
        traces=[TraceSummary(**_summary(qt, uid, email)) for qt, uid, email in page],
        next_before=page[-1][0].created_at if more and page else None,
    )


@router.get("/traces/{query_trace_id}", response_model=TraceDetail)
@limiter.limit(PER_MINUTE_LIMIT)
def get_trace(
    request: Request,  # required by slowapi to key the limiter
    query_trace_id: UUID,
    caller: Caller = Admin,
    session: Session = DbSession,
) -> TraceDetail:
    row = session.execute(
        _traces_with_user().where(QueryTrace.id == query_trace_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    qt, user_id, user_email = row

    info = parse_retrieval_config(qt.retrieval_config)
    rows = session.execute(
        select(RetrievalTrace, Chunk.chunk_text)
        .outerjoin(Chunk, Chunk.id == RetrievalTrace.chunk_id)
        .where(RetrievalTrace.query_trace_id == qt.id)
        .order_by(RetrievalTrace.final_rank)
    ).all()

    candidates = []
    for rt, chunk_text in rows:
        actor = actor_for(rt.provision_citation_id)
        candidates.append(
            TraceCandidate(
                final_rank=rt.final_rank,
                citation_id=rt.provision_citation_id,
                citation_label=citation_label(rt.provision_citation_id),
                chunk_id=rt.chunk_id,
                chunk_preview=(chunk_text or None) and chunk_text[:PREVIEW_CHARS],
                vector_rank=rt.vector_rank,
                lexical_rank=rt.lexical_rank,
                rrf_score=rt.rrf_score,
                similarity=rt.similarity,
                used_in_context=rt.used_in_context,
                actor=actor,
                # Replays the prior's rule (app/retrieval/actor.py) from stored
                # facts. Always False for legacy rows: nothing was recorded.
                downweighted=(
                    info.query_actor is not None
                    and actor is not None
                    and actor != info.query_actor
                ),
            )
        )

    # What the user was shown: the context slice, unless the model abstained,
    # in which case _persist_turn dropped the citations on purpose.
    citations = (
        []
        if qt.abstained
        else [
            TraceCitation(citation_id=c.citation_id, citation_label=c.citation_label)
            for c in candidates
            if c.used_in_context
        ]
    )

    return TraceDetail(
        **_summary(qt, user_id, user_email),
        retrieval=info,
        answer=qt.answer_text,
        citations=citations,
        candidates=candidates,
    )
