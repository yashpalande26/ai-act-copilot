"""Row-level equivalence against the real database: flag on and flag off
write the same message, citation, query_trace and retrieval_trace rows, and
the agentic golden set's gold ids all exist in the corpus. Retrieval and the
model are faked (no embedding, no chat call); persistence is real, inside one
transaction that is rolled back. Skipped without DATABASE_URL."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.db.models import (
    AppUser,
    ChatSession,
    Chunk,
    Citation,
    CorpusVersion,
    Message,
    Provision,
    QueryTrace,
    RetrievalTrace,
)
from app.generation import answer as answer_module
from app.generation.graph import PATH_TAG
from app.retrieval.search import FusedResult, SearchResult

TABLES = (AppUser, ChatSession, Message, Citation, QueryTrace, RetrievalTrace)


@pytest.fixture
def db():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not configured")
    from app.db.session import SessionLocal

    session = SessionLocal()
    real_commit = session.commit
    session.commit = session.flush
    try:
        yield session
    finally:
        session.commit = real_commit
        session.rollback()
        session.close()


def _counts(session):
    return {
        t.__tablename__: session.execute(
            select(func.count()).select_from(t)
        ).scalar_one()
        for t in TABLES
    }


def _real_chunk(session, cv_id):
    """A genuine chunk row so the citation and retrieval_trace FKs hold."""
    chunk = (
        session.execute(
            select(Chunk)
            .where(Chunk.corpus_version_id == cv_id)
            .order_by(Chunk.id)
            .limit(1)
        )
        .scalars()
        .one()
    )
    prov = (
        session.execute(select(Provision).where(Provision.id == chunk.provision_id))
        .scalars()
        .one()
    )
    sr = SearchResult(
        chunk_id=chunk.id,
        citation_id=prov.citation_id,
        citation_label=prov.citation_id,
        chunk_text=chunk.chunk_text,
        similarity=0.6,
        article_heading=None,
    )
    return FusedResult(result=sr, rrf_score=0.01, vector_rank=0, lexical_rank=None)


def _turn(monkeypatch, session, cv_id, chat_id, fused, text):
    monkeypatch.setattr(answer_module, "vector_search", lambda *a, **kw: [])
    monkeypatch.setattr(answer_module, "load_index", lambda cv: object())
    monkeypatch.setattr(answer_module, "bm25_search", lambda *a, **kw: [])
    monkeypatch.setattr(answer_module, "rrf_rank_and_fuse", lambda *a, **kw: fused)
    client = MagicMock()
    resp = MagicMock()
    resp.choices[0].message.content = text
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 3
    client.chat.completions.create.return_value = resp
    monkeypatch.setattr(answer_module, "_get_client", lambda: client)
    return answer_module.generate_grounded_answer(
        session, "what must providers do?", cv_id, chat_id
    )


def _rows(session, chat_id):
    msgs = session.execute(
        select(Message.role, Message.content)
        .where(Message.session_id == chat_id)
        .order_by(Message.created_at, Message.role.desc())
    ).all()
    traces = (
        session.execute(select(QueryTrace).where(QueryTrace.chat_session_id == chat_id))
        .scalars()
        .all()
    )
    assert len(traces) == 1
    t = traces[0]
    cites = session.execute(
        select(Citation.chunk_id, Citation.provision_citation_id)
        .join(Message, Message.id == Citation.message_id)
        .where(Message.session_id == chat_id)
    ).all()
    rtr = session.execute(
        select(
            RetrievalTrace.chunk_id,
            RetrievalTrace.final_rank,
            RetrievalTrace.used_in_context,
        )
        .where(RetrievalTrace.query_trace_id == t.id)
        .order_by(RetrievalTrace.final_rank)
    ).all()
    return {
        "messages": [tuple(m) for m in msgs],
        "citations": sorted(tuple(c) for c in cites),
        "rtrace": [tuple(r) for r in rtr],
        "trace": (
            t.query_text,
            t.answer_text,
            t.abstained,
            t.model,
            t.prompt_tokens,
            t.completion_tokens,
            t.user_id,
        ),
        "retrieval_config": t.retrieval_config,
    }


@pytest.mark.parametrize("answers", [True, False])
def test_flag_on_and_off_write_identical_rows(monkeypatch, db, answers):
    cv = (
        db.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
        .scalars()
        .first()
    )
    before = _counts(db)
    user = AppUser(email=f"graph-db-{uuid4()}@example.com")
    db.add(user)
    db.flush()
    fused = [_real_chunk(db, cv.id)]
    text = (
        "Providers must ensure compliance."
        if answers
        else answer_module.ABSTENTION_TEXT
    )
    shapes = {}
    # Stage 0 equivalence: the graph alone, both agentic nodes pinned off.
    monkeypatch.setenv("AGENTIC_REWRITE", "0")
    monkeypatch.setenv("AGENTIC_GRADE", "0")
    for flag in ("0", "1"):
        monkeypatch.setenv("AGENTIC_RAG", flag)
        chat = ChatSession(user_id=user.id, corpus_version_id=cv.id, title="t")
        db.add(chat)
        db.flush()
        result = _turn(monkeypatch, db, cv.id, chat.id, fused, text)
        shapes[flag] = (
            _rows(db, chat.id),
            result.answer,
            [c.citation_id for c in result.citations],
        )

    off, on = shapes["0"], shapes["1"]
    assert on[1:] == off[1:]
    assert on[0]["messages"] == off[0]["messages"]
    assert on[0]["citations"] == off[0]["citations"]
    assert on[0]["rtrace"] == off[0]["rtrace"]
    assert on[0]["trace"] == off[0]["trace"]
    assert on[0]["retrieval_config"] == off[0]["retrieval_config"] + PATH_TAG
    if answers:
        assert on[0]["citations"] and on[0]["trace"][2] is False
    else:
        assert on[0]["citations"] == [] and on[0]["trace"][2] is True
    # Row diff: the two turns added exactly the same number of rows each.
    after = _counts(db)
    added = {k: after[k] - before[k] for k in after}
    assert (
        added["message"] == 4
        and added["query_trace"] == 2
        and added["retrieval_trace"] == 2
    )
    assert added["citation"] == (2 if answers else 0)


def test_agentic_set_gold_ids_exist_in_corpus(db):
    items = json.loads(
        (Path(__file__).resolve().parents[1] / "evals" / "agentic_set.json").read_text()
    )
    cv = (
        db.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
        .scalars()
        .first()
    )
    wanted = sorted({g for it in items for g in it["gold_citation_ids"]})
    have = set(
        db.execute(
            select(Provision.citation_id).where(
                Provision.corpus_version_id == cv.id, Provision.citation_id.in_(wanted)
            )
        ).scalars()
    )
    assert sorted(set(wanted) - have) == []
