"""FastAPI dependencies for the authenticated, cost-controlled surface."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import (
    DAILY_LIMIT_GLOBAL,
    DAILY_LIMIT_PER_USER,
    SERVICE_TOKEN_ALGORITHM,
    SERVICE_TOKEN_LEEWAY_SECONDS,
    app_env,
    internal_api_secret,
)
from app.db.models import AppUser, ChatSession, QueryTrace
from app.db.session import SessionLocal


class Caller(BaseModel):
    """The identity asserted by the BFF, after signature verification.

    IMPORTANT: a valid token proves "a party holding the signing key asserted
    this identity" - NOT that the end user authenticated. The security boundary
    is key custody plus network isolation (FastAPI ingress restricted to the
    Next.js origin); this token only narrows the exposure window.
    """

    subject: str
    email: str


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def require_service_token(authorization: str | None = Header(default=None)) -> Caller:
    """Verify the short-lived HS256 token minted by the Next.js BFF."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        )
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(
            token,
            internal_api_secret(),
            algorithms=[SERVICE_TOKEN_ALGORITHM],
            # Absorbs clock drift between the Next.js and FastAPI hosts, which
            # on a 60s token would otherwise cause intermittent 401s.
            leeway=SERVICE_TOKEN_LEEWAY_SECONDS,
        )
    except jwt.PyJWTError as exc:
        # Never echo the library's message back - it distinguishes "expired"
        # from "bad signature", which is free information for an attacker.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        ) from exc

    subject, email = claims.get("sub"), claims.get("email")
    if not subject or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        )
    return Caller(subject=str(subject), email=str(email))


def resolve_user(session: Session, caller: Caller) -> AppUser:
    """Get-or-create the app_user row for an authenticated caller."""
    user = (
        session.execute(select(AppUser).where(AppUser.email == caller.email))
        .scalars()
        .first()
    )
    if user is not None:
        return user
    user = AppUser(email=caller.email)
    session.add(user)
    session.commit()
    return user


def get_owned_session(session: Session, user_id: UUID, session_id: UUID) -> ChatSession:
    """Load a chat session the caller owns, or 404.

    404 rather than 403 on purpose, and the same 404 for "no such session" and
    "someone else's session": confirming that a foreign id exists is free
    information for an attacker. Shared by /ask (continue a thread) and the
    history endpoints (list and reopen), so the ownership rule lives once.
    """
    chat = (
        session.execute(select(ChatSession).where(ChatSession.id == session_id))
        .scalars()
        .first()
    )
    if chat is None or chat.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found"
        )
    return chat


def _utc_day_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def calls_today(session: Session, user_id: UUID | None = None) -> int:
    """Authoritative daily usage from query_trace, attributed via
    query_trace -> chat_session -> app_user.

    DB-backed rather than in-memory because slowapi counters reset on every
    restart/deploy - for a money control that means a user could reset their
    quota by waiting for a deploy.

    Two known, bounded gaps: query_trace is written AFTER the answer completes,
    so concurrent in-flight calls are not yet counted; and _write_trace_safe is
    best-effort and swallows failures, so a failed trace write is uncounted.
    The per-minute slowapi cap bounds both to ~10 uncounted calls (~$0.10).

    Scoped to the CURRENT environment (config.app_env), not hardcoded to
    production: each environment has its own budget, so local dev and pytest
    rows can never consume production's quota, and a production instance that
    was deployed without APP_ENV still counts (and protects) its own rows.
    """
    stmt = (
        select(func.count())
        .select_from(QueryTrace)
        .where(QueryTrace.created_at >= _utc_day_start())
        .where(QueryTrace.environment == app_env())
    )
    if user_id is not None:
        stmt = stmt.join(
            ChatSession, ChatSession.id == QueryTrace.chat_session_id
        ).where(ChatSession.user_id == user_id)
    return session.execute(stmt).scalar() or 0


def enforce_daily_quota(session: Session, user: AppUser) -> None:
    """Per-user cap, then a global circuit breaker - the global one covers
    many-accounts abuse, which per-user limits structurally cannot."""
    if calls_today(session, user.id) >= DAILY_LIMIT_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="daily_quota_exceeded",
        )
    if calls_today(session) >= DAILY_LIMIT_GLOBAL:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="service_daily_quota_exceeded",
        )


DbSession = Depends(get_db)
ServiceToken = Depends(require_service_token)
