from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Assessment(Base):
    """A saved assessment: the user's answers plus the decision they produced.

    The answers are the source of truth. Reopening re-runs the deterministic
    engine on them and re-renders provision text from the CURRENT corpus, so a
    saved row is not an immutable snapshot of the quoted text (recorded as a
    known limitation; see the plan of 21 Sep 2026). engine_version and the
    corpus consolidated date say which rules and which text produced the
    decision at save time.

    Not related to the older, unused ClassificationRun table in audit.py,
    which belongs to the five-rule classifier and is dead code to remove in a
    later cleanup.
    """

    __tablename__ = "assessment"
    __table_args__ = (Index("ix_assessment_user_created", "user_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    corpus_version_id: Mapped[int] = mapped_column(ForeignKey("corpus_version.id"))
    environment: Mapped[str]  # config.app_env() at save time, like query_trace
    engine_version: Mapped[str]
    corpus_consolidated_date: Mapped[str]
    answers: Mapped[dict] = mapped_column(JSONB)
    headline: Mapped[str]
    roles: Mapped[list] = mapped_column(JSONB)
    obligation_citation_ids: Mapped[list] = mapped_column(JSONB)
    penalties: Mapped[dict] = mapped_column(JSONB)
    # Provenance of the answers: "form" (typed in) or "extracted" (pre-filled
    # from a description by the extraction run below, then confirmed and
    # possibly edited by the user; what is stored is what the user confirmed).
    source: Mapped[str] = mapped_column(server_default="form")
    extraction_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extraction_run.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
