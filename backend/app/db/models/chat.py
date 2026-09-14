from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    corpus_version_id: Mapped[int] = mapped_column(ForeignKey("corpus_version.id"))
    title: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Message(Base):
    __tablename__ = "message"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_session.id"))
    role: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Citation(Base):
    __tablename__ = "citation"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("message.id"))
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("chunk.id"))
    provision_citation_id: Mapped[str]
    quoted_text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int | None]
    char_end: Mapped[int | None]
    verified: Mapped[bool] = mapped_column(default=False)
