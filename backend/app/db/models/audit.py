from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ClassificationRun(Base):
    __tablename__ = "classification_run"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id"))
    corpus_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("corpus_version.id")
    )
    input_payload: Mapped[dict] = mapped_column(JSONB)
    risk_tier: Mapped[str]
    triggering_article: Mapped[str | None]
    rationale: Mapped[str] = mapped_column(Text)
    engine_version: Mapped[str]
    prev_hash: Mapped[str | None]
    row_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
