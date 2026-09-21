from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
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


class QueryTrace(Base):
    """Engineering telemetry for one copilot turn: query, answer, timing,
    tokens, provenance. Separate from message/citation (the product chat
    store) on purpose - this is the observability/eval store."""

    __tablename__ = "query_trace"
    __table_args__ = (Index("ix_query_trace_created_at", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chat_session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_session.id"))
    corpus_version_id: Mapped[int] = mapped_column(ForeignKey("corpus_version.id"))
    query_text: Mapped[str] = mapped_column(Text)
    answer_text: Mapped[str] = mapped_column(Text)
    abstained: Mapped[bool]
    model: Mapped[str]
    # Which deployment wrote this row ("production" / "dev" / "test", see
    # config.APP_ENVIRONMENTS). The daily quota counts only rows from the
    # current environment, so non-production traffic cannot consume
    # production's budget. server_default covers rows that predate the column.
    environment: Mapped[str] = mapped_column(server_default="dev")
    retrieval_config: Mapped[str]  # e.g. "hybrid" - plain str, not an enum
    retrieval_latency_ms: Mapped[int]
    generation_latency_ms: Mapped[
        int | None
    ]  # None on pre-LLM abstention (no LLM call made)
    prompt_tokens: Mapped[int | None]  # None for the same reason
    completion_tokens: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RetrievalTrace(Base):
    """One row per retrieved candidate chunk for a QueryTrace - the
    diagnostics behind a turn's citations."""

    __tablename__ = "retrieval_trace"
    __table_args__ = (Index("ix_retrieval_trace_query_trace_id", "query_trace_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    query_trace_id: Mapped[UUID] = mapped_column(ForeignKey("query_trace.id"))
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("chunk.id"))
    provision_citation_id: Mapped[str]
    final_rank: Mapped[int]  # 1-indexed position in the full fused candidate list
    rrf_score: Mapped[float | None]
    vector_rank: Mapped[int | None]  # mirrors FusedResult.vector_rank
    lexical_rank: Mapped[int | None]  # mirrors FusedResult.lexical_rank
    # Cosine similarity when vector_rank is set; ts_rank_cd score when only
    # lexical_rank is set. Same source ambiguity as SearchResult.similarity
    # in app/retrieval/search.py - not a new problem introduced here.
    similarity: Mapped[float | None]
    used_in_context: Mapped[
        bool
    ]  # did this candidate make the top final_context_size sent to the LLM
