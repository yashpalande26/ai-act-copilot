import os
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import (
    AppUser,
    ChatSession,
    Citation,
    CorpusVersion,
    Message,
    QueryTrace,
)
from app.generation import answer as answer_module
from app.retrieval.bm25_index import StaleIndexError
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
    # Production's lexical leg is BM25; pretend an index exists so these tests
    # exercise the hybrid_bm25 path rather than the degraded one.
    monkeypatch.setattr(answer_module, "load_index", lambda cv: object())
    monkeypatch.setattr(answer_module, "bm25_search", lambda *a, **kw: [])
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
        session,
        "irrelevant query",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        write_trace=False,
    )

    fake_client.chat.completions.create.assert_not_called()
    assert result.answer == answer_module.ABSTENTION_TEXT
    assert result.citations == []
    messages = [o for o in session.added if isinstance(o, Message)]
    citations = [o for o in session.added if isinstance(o, Citation)]
    # Both the user's query and the assistant's refusal are persisted, even
    # when the LLM is never called.
    assert len(messages) == 2
    assert {m.role for m in messages} == {"user", "assistant"}
    assert messages[0].content == "irrelevant query"
    assistant_message = next(m for m in messages if m.role == "assistant")
    assert assistant_message.content == answer_module.ABSTENTION_TEXT
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
        session,
        "some query",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        write_trace=False,
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
        session,
        "query",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        write_trace=False,
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
        session,
        "query",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        write_trace=False,
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
        session,
        "query",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        write_trace=False,
    )

    assert result.answer == answer_module.ABSTENTION_TEXT
    assert result.citations == []
    citations = [o for o in session.added if isinstance(o, Citation)]
    assert len(citations) == 0


# --- BM25 lexical leg: degradation boundary -----------------------------


def _captured_trace_config(session):
    traces = [o for o in session.added if isinstance(o, QueryTrace)]
    assert len(traces) == 1
    return traces[0].retrieval_config


def _run_one_turn(monkeypatch, session):
    """A normal grounded turn with the trace enabled, so retrieval_config is
    actually written."""
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _make_llm_response("An answer.")
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake_client)
    return answer_module.generate_grounded_answer(
        session,
        "query",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        write_trace=True,
    )


def test_index_present_uses_hybrid_bm25_and_records_it(monkeypatch):
    _patch_retrieval(monkeypatch, [_fr(1, citation_id="art_1")])
    called = {}
    monkeypatch.setattr(
        answer_module,
        "bm25_search",
        lambda *a, **kw: called.setdefault("yes", True) or [],
    )
    session = _make_session()

    result = _run_one_turn(monkeypatch, session)

    assert result.answer == "An answer."
    assert called.get("yes") is True
    assert _captured_trace_config(session) == "hybrid_bm25|actor=none"


def test_trace_is_stamped_with_current_environment(monkeypatch):
    _patch_retrieval(monkeypatch, [_fr(1, citation_id="art_1")])
    session = _make_session()

    _run_one_turn(monkeypatch, session)

    traces = [o for o in session.added if isinstance(o, QueryTrace)]
    assert len(traces) == 1
    # conftest forces APP_ENV=test, so a test-written trace can never count
    # against production's daily quota.
    assert traces[0].environment == "test"


def test_actor_prior_reorders_context_and_is_recorded_in_trace(monkeypatch):
    # A deployer question with a provider chunk fused ABOVE a deployer chunk.
    provider_first = [
        FusedResult(
            result=_sr(1, citation_id="art_16.pt_a"),
            rrf_score=0.012,
            vector_rank=0,
            lexical_rank=0,
        ),
        FusedResult(
            result=_sr(2, citation_id="art_26.par_1"),
            rrf_score=0.010,
            vector_rank=1,
            lexical_rank=1,
        ),
    ]
    _patch_retrieval(monkeypatch, provider_first)
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _make_llm_response("An answer.")
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake_client)
    session = _make_session()

    result = answer_module.generate_grounded_answer(
        session,
        "What must a deployer of a high-risk AI system do?",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        write_trace=True,
    )

    # 0.012 * 0.25 = 0.003 < 0.010, so the deployer chunk now leads.
    assert [c.citation_id for c in result.citations] == ["art_26.par_1", "art_16.pt_a"]
    assert _captured_trace_config(session) == (
        f"hybrid_bm25|actor=deployer|factor={answer_module.ACTOR_MISMATCH_FACTOR}"
    )


def test_missing_index_degrades_without_calling_bm25(monkeypatch, capsys):
    _patch_retrieval(monkeypatch, [_fr(1, citation_id="art_1")])
    monkeypatch.setattr(answer_module, "load_index", lambda cv: None)

    def _boom(*a, **kw):
        raise AssertionError("bm25_search must not run when no index exists")

    monkeypatch.setattr(answer_module, "bm25_search", _boom)
    session = _make_session()

    result = _run_one_turn(monkeypatch, session)

    assert result.answer == "An answer."
    assert _captured_trace_config(session) == "vector_only_degraded|actor=none"
    # A missing index means the deploy step never ran - it must be loud, not
    # only visible in the trace table.
    stderr = capsys.readouterr().err
    assert "ACTION REQUIRED" in stderr
    assert "build_bm25_index.py" in stderr


def test_stale_index_degrades_loudly_instead_of_raising(monkeypatch, capsys):
    _patch_retrieval(monkeypatch, [_fr(1, citation_id="art_1")])

    def _stale(cv):
        raise StaleIndexError("built for corpus_version 999, not 1")

    monkeypatch.setattr(answer_module, "load_index", _stale)
    session = _make_session()

    result = _run_one_turn(monkeypatch, session)

    # The whole point: a stale index must not take the copilot down, and must
    # not serve BM25 results resolved against the wrong chunk_id mapping.
    assert result.answer == "An answer."
    assert _captured_trace_config(session) == "vector_only_degraded|actor=none"
    stderr = capsys.readouterr().err
    assert "ACTION REQUIRED" in stderr
    assert "build_bm25_index.py" in stderr


def test_unexpected_bm25_failure_degrades_under_a_distinct_banner(monkeypatch, capsys):
    _patch_retrieval(monkeypatch, [_fr(1, citation_id="art_1")])

    def _corrupt(cv):
        raise RuntimeError("corrupt index file")

    monkeypatch.setattr(answer_module, "load_index", _corrupt)
    session = _make_session()

    result = _run_one_turn(monkeypatch, session)

    assert result.answer == "An answer."
    assert _captured_trace_config(session) == "vector_only_degraded|actor=none"
    stderr = capsys.readouterr().err
    # Distinct from the stale banner, so a real bug never hides behind the
    # expected operational case.
    assert "UNEXPECTED" in stderr
    assert "ACTION REQUIRED" not in stderr


def test_trace_write_failure_does_not_affect_answer_or_product_data(
    monkeypatch, capsys
):
    fused = [_fr(1, citation_id="art_1")]
    _patch_retrieval(monkeypatch, fused)
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _make_llm_response(
        "A real grounded answer (Article 1)."
    )
    monkeypatch.setattr(answer_module, "_get_client", lambda: fake_client)

    session = _make_session()
    original_add = session.add.side_effect

    def add_with_trace_failure(obj):
        if isinstance(obj, QueryTrace):
            # Simulating an infra/DB failure, not a real type error.
            raise RuntimeError("simulated DB failure writing query_trace")  # noqa: TRY004
        original_add(obj)

    session.add.side_effect = add_with_trace_failure

    result = answer_module.generate_grounded_answer(
        session, "some query", corpus_version_id=1, chat_session_id=uuid4()
    )

    # The answer itself is unaffected by the trace-write failure.
    assert result.answer == "A real grounded answer (Article 1)."
    assert [c.chunk_id for c in result.citations] == [1]

    # Product data (both messages + the citation) still persisted intact -
    # _persist_turn's own transaction already committed before the trace
    # write was even attempted.
    messages = [o for o in session.added if isinstance(o, Message)]
    citations = [o for o in session.added if isinstance(o, Citation)]
    assert len(messages) == 2  # user + assistant
    assert len(citations) == 1
    assert not any(isinstance(o, QueryTrace) for o in session.added)

    # The failure was logged, not silently lost.
    assert "trace write failed" in capsys.readouterr().err


@pytest.mark.live
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
            session,
            "credit scoring high risk",
            latest.id,
            chat_session.id,
            write_trace=False,
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


# --- dense anchor and abstention tolerance (22 Sep 2026) -----------------------


def _srs(chunk_id, citation_id, similarity):
    return _sr(chunk_id, citation_id).model_copy(update={"similarity": similarity})


def _fused(chunk_id, citation_id, sim=0.2, vr=None, lr=0):
    return FusedResult(
        result=_srs(chunk_id, citation_id, sim),
        rrf_score=0.01,
        vector_rank=vr,
        lexical_rank=lr,
    )


def test_dense_anchor_promotes_a_confident_top_vector_hit_that_fusion_dropped():
    fused = [_fused(i, f"art_{i}") for i in range(1, 26)]  # lexical-only saturation
    top = _srs(99, "art_3.pt_3", 0.52)
    out, anchored = answer_module.apply_dense_anchor(
        fused, [top], floor=0.45, context_size=15
    )
    assert anchored and out[5].result.chunk_id == 99 and out[5].lexical_rank is None
    # The fused top five are untouched; the rest shift down by one.
    assert [f.result.chunk_id for f in out[:5]] == [1, 2, 3, 4, 5]
    assert len(out) == 25 and out[6].result.chunk_id == 6


def test_dense_anchor_does_nothing_below_the_floor_or_when_already_in_context():
    fused = [_fused(i, f"art_{i}") for i in range(1, 26)]
    out, anchored = answer_module.apply_dense_anchor(
        fused, [_srs(99, "x", 0.44)], floor=0.45
    )
    assert not anchored and out is fused
    present = _srs(7, "art_7", 0.9)  # chunk 7 sits at rank 7 already
    out, anchored = answer_module.apply_dense_anchor(fused, [present], floor=0.45)
    assert not anchored and out is fused
    assert answer_module.apply_dense_anchor(fused, [], floor=0.45) == (fused, False)


def test_dense_anchor_moves_a_hit_that_sat_outside_the_context_slice():
    fused = [_fused(i, f"art_{i}") for i in range(1, 26)]
    beyond = fused[20].result.model_copy(update={"similarity": 0.6})
    out, anchored = answer_module.apply_dense_anchor(
        fused, [beyond], floor=0.45, context_size=15
    )
    assert anchored and out[5].result.chunk_id == beyond.chunk_id
    assert [f.result.chunk_id for f in out].count(beyond.chunk_id) == 1
    assert len(out) == 25


@pytest.mark.parametrize(
    "text",
    [
        answer_module.ABSTENTION_TEXT,
        f'"{answer_module.ABSTENTION_TEXT}"',
        f"“{answer_module.ABSTENTION_TEXT}”",
        f"  {answer_module.ABSTENTION_TEXT}  ",
        answer_module.ABSTENTION_TEXT.rstrip("."),
    ],
)
def test_quoted_or_unpunctuated_abstention_is_still_an_abstention(text):
    assert answer_module.is_abstention(text)


def test_a_real_answer_is_not_an_abstention():
    assert not answer_module.is_abstention(
        "Providers must ensure compliance with Section 2."
    )
    assert not answer_module.is_abstention(
        answer_module.ABSTENTION_TEXT + " However, Article 6 says..."
    )
