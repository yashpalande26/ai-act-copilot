from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExtractionRun(Base):
    """One paid free-text extraction: the description in, the model's
    structured answers and their provenance out. Two jobs:

    1. The quota record. deps.calls_today counts these rows together with
       query_trace in the same environment, so an extraction spends the same
       daily budget as a chat turn (decision C1/C6, 21 Sep 2026). Unlike
       query_trace this write is NOT best-effort: no row, no response.
    2. Provenance. assessment.extraction_run_id points here when a saved
       assessment started from a description, so the record can say
       "pre-filled from a description on <date>, confirmed by the user".

    `description` is the user's own text about their system: business
    information, readable through the admin allowlist only (same posture as
    query_trace.query_text; decision C5).
    """

    __tablename__ = "extraction_run"
    __table_args__ = (Index("ix_extraction_run_user_created", "user_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    corpus_version_id: Mapped[int] = mapped_column(ForeignKey("corpus_version.id"))
    environment: Mapped[str]  # config.app_env(), like query_trace
    model: Mapped[str]  # registry key, e.g. "openai:gpt-4o-mini"
    prompt_version: Mapped[str]  # extraction.prompt_version(): prompt + schema hash
    status: Mapped[str]  # "ok" | "refused" | "failed"
    input_chars: Mapped[int]
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    latency_ms: Mapped[int]
    description: Mapped[str] = mapped_column(Text)
    extracted: Mapped[dict | None] = mapped_column(JSONB)  # raw model output
    provenance: Mapped[dict | None] = mapped_column(JSONB)  # field -> inferred|unknown
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
