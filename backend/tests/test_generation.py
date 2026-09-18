import os
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import AppUser, ChatSession, Citation, CorpusVersion, Message
from app.generation import answer as answer_module
from app.retrieval.search import FusedResult, SearchResult


def _sr(chunk_id, citation_id="art_1", chunk_text="some text"):
    return SearchResult(
        chunk_id=chunk_id,
        citation_id=citation_id,
        citation_label=citation_id,
        chunk_text=chunk_text,
        similarity=0.5,
        article_heading=None,
    )


def _fr(chunk_id, **kwargs):
    return FusedResult(
        result=_sr(chunk_id, **kwargs), rrf_score=0.01, vector_rank=0, lexical_rank=None
    )


def _make_llm_response(text):
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _patch_retrieval(monkeypatch, fused_result):
    monkeypatch.setattr(answer_module, "vector_search", lambda *a, **kw: [])
    monkeypatch.setattr(answer_module, "keyword_search", lambda *a, **kw: [])
    monkeypatch.setattr(
        answer_module, "rrf_rank_and_fuse", lambda *a, **kw: fused_result
    )


def _make_session():
    """A MagicMock session whose .add() simulates what a real flush would do:
    assigns a fresh id to any Message added (SQLAlchemy's default=uuid4 is a
    client-side default only evaluated at real flush time, which never
    happens against a mocked session otherwise)."""
    session = MagicMock()
    added = []

    def fake_add(obj):
        added.append(obj)
        if isinstance(obj, Message) and obj.id is None:
            obj.id = uuid4()

    session.add.side_effect = fake_add
    session.added = added
    return session


def test_abstention_when_retrieval_empty_llm_not_called(monkeypatch):
    _patch_retrieval(monkeypatch, [])
    fake_client = MagicMock()
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake_client)
    session = _make_session()

    result = answer_module.generate_grounded_answer(
        session, "irrelevant query", corpus_version_id=1, chat_session_id=uuid4()
    )

    fake_client.chat.completions.create.assert_not_called()
    assert result.answer == answer_module.ABSTENTION_TEXT
    assert result.citations == []
    messages = [o for o in session.added if isinstance(o, Message)]
    citations = [o for o in session.added if isinstance(o, Citation)]
    assert len(messages) == 1
    assert messages[0].content == answer_module.ABSTENTION_TEXT
    assert len(citations) == 0


def test_grounded_path_returns_answer_and_matching_citations(monkeypatch):
    fused = [_fr(1, citation_id="art_1"), _fr(2, citation_id="art_2")]
    _patch_retrieval(monkeypatch, fused)
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _make_llm_response(
        "The answer is X (Article 1)."
    )
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake_client)
    session = _make_session()

    result = answer_module.generate_grounded_answer(
        session, "some query", corpus_version_id=1, chat_session_id=uuid4()
    )

    assert result.answer == "The answer is X (Article 1)."
    assert [c.chunk_id for c in result.citations] == [1, 2]
    citations = [o for o in session.added if isinstance(o, Citation)]
    assert len(citations) == 2
    assert {c.chunk_id for c in citations} == {1, 2}


def test_temperature_zero_passed_to_llm(monkeypatch):
    _patch_retrieval(monkeypatch, [_fr(1)])
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _make_llm_response("answer")
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake_client)
    session = _make_session()

    answer_module.generate_grounded_answer(
        session, "query", corpus_version_id=1, chat_session_id=uuid4()
    )

    _, kwargs = fake_client.chat.completions.create.call_args
    assert kwargs["temperature"] == 0


def test_citation_quoted_text_not_derived_from_llm_output(monkeypatch):
    fused = [_fr(1, citation_id="art_1", chunk_text="ORIGINAL RETRIEVED TEXT")]
    _patch_retrieval(monkeypatch, fused)
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _make_llm_response(
        "A completely different paraphrase the model wrote."
    )
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake_client)
    session = _make_session()

    answer_module.generate_grounded_answer(
        session, "query", corpus_version_id=1, chat_session_id=uuid4()
    )

    citations = [o for o in session.added if isinstance(o, Citation)]
    assert citations[0].quoted_text == "ORIGINAL RETRIEVED TEXT"


def test_post_llm_abstention_drops_citations(monkeypatch):
    fused = [_fr(1), _fr(2)]  # retrieval DID find chunks
    _patch_retrieval(monkeypatch, fused)
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _make_llm_response(
        answer_module.ABSTENTION_TEXT
    )
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake_client)
    session = _make_session()

    result = answer_module.generate_grounded_answer(
        session, "query", corpus_version_id=1, chat_session_id=uuid4()
    )

    assert result.answer == answer_module.ABSTENTION_TEXT
    assert result.citations == []
    citations = [o for o in session.added if isinstance(o, Citation)]
    assert len(citations) == 0


def test_grounded_generation_integration_real_query():
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("DATABASE_URL"):
        pytest.skip("OPENAI_API_KEY/DATABASE_URL not configured")

    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        latest = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        if latest is None:
            pytest.skip("No corpus_version found; run ingest.py first")

        # Real FK chain required by the schema: a throwaway AppUser + ChatSession.
        user = AppUser(email=f"integration-test-{uuid4()}@example.com")
        session.add(user)
        session.flush()
        chat_session = ChatSession(user_id=user.id, corpus_version_id=latest.id)
        session.add(chat_session)
        session.flush()
        session.commit()

        result = answer_module.generate_grounded_answer(
            session, "credit scoring high risk", latest.id, chat_session.id
        )

        print("\n=== Answer ===")
        print(result.answer)
        print("=== Citations ===")
        for c in result.citations:
            print(f"  {c.citation_label}: {c.chunk_text[:80]}")

        assert result.answer != answer_module.ABSTENTION_TEXT
        assert len(result.citations) > 0
    finally:
        session.close()
