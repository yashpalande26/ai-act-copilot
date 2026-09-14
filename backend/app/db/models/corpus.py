from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CorpusVersion(Base):
    __tablename__ = "corpus_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    celex: Mapped[str] = mapped_column(unique=True)
    eli: Mapped[str | None]
    title: Mapped[str]
    consolidated_date: Mapped[date]
    valid_from: Mapped[date]
    valid_to: Mapped[date | None]
    source_url: Mapped[str]
    content_hash: Mapped[str]
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Provision(Base):
    __tablename__ = "provision"
    __table_args__ = (UniqueConstraint("corpus_version_id", "citation_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    corpus_version_id: Mapped[int] = mapped_column(ForeignKey("corpus_version.id"))
    citation_id: Mapped[str]
    eid: Mapped[str | None]
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("provision.id"))
    unit_type: Mapped[str]
    number: Mapped[str]
    heading: Mapped[str | None]
    text_content: Mapped[str] = mapped_column(Text)
    amendment_marker: Mapped[str | None]
    ordinal: Mapped[int]


class ProvisionReference(Base):
    __tablename__ = "provision_reference"

    id: Mapped[int] = mapped_column(primary_key=True)
    corpus_version_id: Mapped[int] = mapped_column(ForeignKey("corpus_version.id"))
    from_provision_id: Mapped[int] = mapped_column(ForeignKey("provision.id"))
    to_citation_id: Mapped[str]
    to_provision_id: Mapped[int | None] = mapped_column(ForeignKey("provision.id"))
    raw_text: Mapped[str]


class Chunk(Base):
    __tablename__ = "chunk"

    id: Mapped[int] = mapped_column(primary_key=True)
    corpus_version_id: Mapped[int] = mapped_column(ForeignKey("corpus_version.id"))
    provision_id: Mapped[int] = mapped_column(ForeignKey("provision.id"))
    parent_provision_id: Mapped[int | None] = mapped_column(ForeignKey("provision.id"))
    chunk_text: Mapped[str] = mapped_column(Text)
    index_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    char_start: Mapped[int | None]
    char_end: Mapped[int | None]
    content_hash: Mapped[str]
    token_count: Mapped[int | None]
