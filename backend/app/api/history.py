"""GET /sessions and GET /sessions/{id}: the signed-in user's conversation
history, read straight from the rows /ask already persists.

Reads only. No OpenAI call, no quota check (browsing history must never spend
money or consume the question budget), but the same service-token gate and
per-minute limit as every other endpoint. Ownership is enforced in the query
itself (WHERE user_id = the caller) and by deps.get_owned_session, never by
filtering after the fact.

Two facts about the stored rows shape the code here:
  - _persist_turn inserts the user and assistant messages in one transaction,
    so they share a created_at. Ordering needs a role tiebreak.
  - An abstained turn is stored as ABSTENTION_TEXT with zero citations; it is
    recognised by content so the client can render the abstention card.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    Caller,
    DbSession,
    ServiceToken,
    get_owned_session,
    resolve_user,
)
from app.config import PER_MINUTE_LIMIT
from app.db.models import ChatSession, Citation, Message
from app.generation.answer import ABSTENTION_TEXT
from app.ingestion.chunker import citation_label
from app.rate_limit import limiter

router = APIRouter()

TITLE_MAX_CHARS = 120
UNTITLED = "Untitled chat"

# user before assistant when created_at ties; id last so the order is total.
MESSAGE_ORDER = (
    Message.created_at,
    case((Message.role == "user", 0), else_=1),
    Message.id,
)


def derive_title(text: str, max_chars: int = TITLE_MAX_CHARS) -> str:
    """A session title from its first question: whitespace collapsed, cut at
    the last word boundary before max_chars, one ellipsis if truncated."""
    flat = " ".join(text.split())
    if len(flat) <= max_chars:
        return flat
    cut = flat[:max_chars]
    # A word that ends exactly at the limit is kept whole; otherwise drop the
    # partial word.
    if flat[max_chars] != " " and " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:.") + "…"


class SessionSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    message_count: int


class SessionList(BaseModel):
    sessions: list[SessionSummary]


class SessionCitation(BaseModel):
    citation_id: str
    citation_label: str
    quoted_text: str


class SessionMessage(BaseModel):
    id: UUID
    role: str
    content: str
    abstained: bool
    created_at: datetime
    citations: list[SessionCitation]


class SessionDetail(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    messages: list[SessionMessage]


def _first_question_subquery():
    return (
        select(Message.content)
        .where(Message.session_id == ChatSession.id, Message.role == "user")
        .order_by(*MESSAGE_ORDER)
        .limit(1)
        .correlate(ChatSession)
        .scalar_subquery()
    )


@router.get("/sessions", response_model=SessionList)
@limiter.limit(PER_MINUTE_LIMIT)
def list_sessions(
    request: Request,  # required by slowapi to key the limiter
    limit: int = Query(default=50, ge=1, le=200),
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> SessionList:
    user = resolve_user(session, caller)
    first_question = _first_question_subquery()
    rows = session.execute(
        select(
            ChatSession.id,
            ChatSession.title,
            ChatSession.created_at,
            func.count(Message.id),
            first_question,
        )
        # Inner join: a session that never got a message (the turn failed
        # after the row was created) has nothing to reopen, so it is hidden.
        .join(Message, Message.session_id == ChatSession.id)
        .where(ChatSession.user_id == user.id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.created_at.desc())
        .limit(limit)
    ).all()
    return SessionList(
        sessions=[
            SessionSummary(
                id=sid,
                title=title or (derive_title(first) if first else UNTITLED),
                created_at=created,
                message_count=count,
            )
            for sid, title, created, count, first in rows
        ]
    )


@router.get("/sessions/{session_id}", response_model=SessionDetail)
@limiter.limit(PER_MINUTE_LIMIT)
def get_session(
    request: Request,  # required by slowapi to key the limiter
    session_id: UUID,
    caller: Caller = ServiceToken,
    session: Session = DbSession,
) -> SessionDetail:
    user = resolve_user(session, caller)
    chat = get_owned_session(session, user.id, session_id)

    messages = (
        session.execute(
            select(Message)
            .where(Message.session_id == chat.id)
            .order_by(*MESSAGE_ORDER)
        )
        .scalars()
        .all()
    )
    by_message: dict[UUID, list[SessionCitation]] = {m.id: [] for m in messages}
    if messages:
        for c in (
            session.execute(
                select(Citation)
                .where(Citation.message_id.in_(list(by_message)))
                .order_by(Citation.id)
            )
            .scalars()
            .all()
        ):
            by_message[c.message_id].append(
                SessionCitation(
                    citation_id=c.provision_citation_id,
                    citation_label=citation_label(c.provision_citation_id),
                    quoted_text=c.quoted_text,
                )
            )

    first_user = next((m.content for m in messages if m.role == "user"), None)
    return SessionDetail(
        id=chat.id,
        title=chat.title or (derive_title(first_user) if first_user else UNTITLED),
        created_at=chat.created_at,
        messages=[
            SessionMessage(
                id=m.id,
                role=m.role,
                content=m.content,
                abstained=(m.role == "assistant" and m.content == ABSTENTION_TEXT),
                created_at=m.created_at,
                citations=by_message[m.id],
            )
            for m in messages
        ],
    )
