import os
from collections import namedtuple
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.db.models import Chunk, CorpusVersion, Provision
from app.retrieval import search as search_module
from app.retrieval.search import SearchResult


def _row(chunk_id, citation_id, chunk_text, distance, ancestor_heading=None):
    chunk = Chunk(
        id=chunk_id, chunk_text=chunk_text, index_text="ignored", embedding=None
    )
    provision = Provision(citation_id=citation_id)
    ancestor = (
        Provision(heading=ancestor_heading) if ancestor_heading is not None else None
    )
    return (chunk, provision, ancestor, distance)


def _make_session(rows):
    session = MagicMock()
    session.execute.return_value.all.return_value = rows
    return session


def test_vector_search_maps_rows_to_search_results(monkeypatch):
    monkeypatch.setattr(search_module, "embed_query", lambda text: [0.1, 0.2, 0.3])
    rows = [
        _row(
            1,
            "art_6.par_2.pt_a",
            "text a",
            distance=0.1,
            ancestor_heading="Classification rules",
        )
    ]
    session = _make_session(rows)

    results = search_module.vector_search(
        session, "query", corpus_version_id=1, top_k=5
    )

    assert len(results) == 1
    r = results[0]
    assert r.chunk_id == 1
    assert r.citation_id == "art_6.par_2.pt_a"
    assert r.citation_label == "Article 6, paragraph 2, point (a)"
    assert r.chunk_text == "text a"
    assert r.similarity == 0.9
    assert r.article_heading == "Classification rules"


def test_vector_search_applies_min_similarity_filter(monkeypatch):
    monkeypatch.setattr(search_module, "embed_query", lambda text: [0.1])
    rows = [
        _row(1, "art_1", "high sim", distance=0.1),  # similarity 0.9
        _row(2, "art_2", "low sim", distance=0.8),  # similarity 0.2
    ]
    session = _make_session(rows)

    results = search_module.vector_search(
        session, "query", corpus_version_id=1, top_k=5, min_similarity=0.5
    )

    assert len(results) == 1
    assert results[0].citation_id == "art_1"


def test_vector_search_respects_top_k(monkeypatch):
    monkeypatch.setattr(search_module, "embed_query", lambda text: [0.1])
    rows = [_row(i, f"art_{i}", f"text {i}", distance=0.1 * i) for i in range(1, 6)]
    session = _make_session(rows)

    results = search_module.vector_search(
        session, "query", corpus_version_id=1, top_k=3
    )

    assert len(results) == 3


# --- keyword_search ---------------------------------------------------

_KwRow = namedtuple(
    "_KwRow", ["chunk_id", "chunk_text", "citation_id", "article_heading", "rank_score"]
)


def _make_kw_session(rows):
    session = MagicMock()
    session.execute.return_value.all.return_value = rows
    return session


def test_keyword_search_maps_rows_to_search_results():
    rows = [
        _KwRow(
            1, "credit scoring text", "art_6.par_2.pt_a", "Classification rules", 0.55
        )
    ]
    session = _make_kw_session(rows)

    results = search_module.keyword_search(
        session, "credit scoring", corpus_version_id=1
    )

    assert len(results) == 1
    r = results[0]
    assert r.chunk_id == 1
    assert r.citation_id == "art_6.par_2.pt_a"
    assert r.citation_label == "Article 6, paragraph 2, point (a)"
    assert r.chunk_text == "credit scoring text"
    assert r.similarity == 0.55
    assert r.article_heading == "Classification rules"


def test_keyword_search_applies_threshold_filter():
    rows = [
        _KwRow(1, "strong match", "art_1", None, 0.5),
        _KwRow(2, "weak match", "art_2", None, 0.05),
    ]
    session = _make_kw_session(rows)

    results = search_module.keyword_search(
        session, "query", corpus_version_id=1, threshold=0.1
    )

    assert len(results) == 1
    assert results[0].citation_id == "art_1"


# --- rrf_rank_and_fuse --------------------------------------------------


def _sr(chunk_id: int, citation_id: str) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        citation_id=citation_id,
        citation_label=citation_id,
        chunk_text=f"text for {citation_id}",
        similarity=0.5,
        article_heading=None,
    )


def test_rrf_hand_calculated_top_3():
    a, b, c, d = _sr(1, "A"), _sr(2, "B"), _sr(3, "C"), _sr(4, "D")
    vector_results = [a, b, c]  # ranks 0, 1, 2
    lexical_results = [b, a, d]  # ranks 0, 1, 2
    k = 60

    fused = search_module.rrf_rank_and_fuse(
        vector_results,
        lexical_results,
        vector_weight=0.7,
        lexical_weight=0.3,
        k=k,
        top_k=3,
    )

    expected_a = 0.7 * (1 / (k + 0 + 1)) + 0.3 * (1 / (k + 1 + 1))
    expected_b = 0.7 * (1 / (k + 1 + 1)) + 0.3 * (1 / (k + 0 + 1))
    expected_c = 0.7 * (1 / (k + 2 + 1))

    assert [f.result.citation_id for f in fused] == ["A", "B", "C"]
    assert fused[0].rrf_score == pytest.approx(expected_a)
    assert fused[1].rrf_score == pytest.approx(expected_b)
    assert fused[2].rrf_score == pytest.approx(expected_c)


def test_rrf_chunk_in_both_lists_ranks_above_single_list_chunk():
    both = _sr(1, "BOTH")
    single = _sr(2, "SINGLE")

    fused = search_module.rrf_rank_and_fuse(
        vector_results=[both, single],  # both: rank 0, single: rank 1
        lexical_results=[both],  # both: rank 0
    )

    assert [f.result.citation_id for f in fused] == ["BOTH", "SINGLE"]
    assert fused[0].rrf_score > fused[1].rrf_score


def test_rrf_weight_imbalance_flips_order():
    vector_favorite = _sr(1, "VECTOR_FAV")  # rank 0 in vector, absent from lexical
    lexical_favorite = _sr(2, "LEXICAL_FAV")  # rank 0 in lexical, absent from vector

    vector_heavy = search_module.rrf_rank_and_fuse(
        vector_results=[vector_favorite],
        lexical_results=[lexical_favorite],
        vector_weight=0.9,
        lexical_weight=0.1,
    )
    lexical_heavy = search_module.rrf_rank_and_fuse(
        vector_results=[vector_favorite],
        lexical_results=[lexical_favorite],
        vector_weight=0.1,
        lexical_weight=0.9,
    )

    assert vector_heavy[0].result.citation_id == "VECTOR_FAV"
    assert lexical_heavy[0].result.citation_id == "LEXICAL_FAV"


def test_rrf_absent_term_contributes_zero():
    vector_only = _sr(1, "VECTOR_ONLY")
    k = 60

    fused = search_module.rrf_rank_and_fuse(
        vector_results=[vector_only],
        lexical_results=[],
        vector_weight=0.7,
        lexical_weight=0.3,
        k=k,
    )

    assert len(fused) == 1
    assert fused[0].vector_rank == 0
    assert fused[0].lexical_rank is None
    assert fused[0].rrf_score == pytest.approx(0.7 * (1 / (k + 0 + 1)))


# --- integration (real DB + real OpenAI embedding call) -----------------


@pytest.mark.live
def test_hybrid_search_integration_real_query():
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

        query = "Article 6(2) requirements"
        vector_results = search_module.vector_search(
            session, query, latest.id, top_k=10
        )
        lexical_results = search_module.keyword_search(
            session, query, latest.id, top_k=10
        )
        fused = search_module.rrf_rank_and_fuse(
            vector_results, lexical_results, top_k=10
        )

        print("\n=== Vector results ===")
        for r in vector_results:
            print(f"  [{r.similarity:.3f}] {r.citation_label}: {r.chunk_text[:80]}")
        print("=== Lexical results ===")
        for r in lexical_results:
            print(f"  [{r.similarity:.3f}] {r.citation_label}: {r.chunk_text[:80]}")
        print("=== Fused results ===")
        for f in fused:
            print(
                f"  [{f.rrf_score:.5f}] {f.result.citation_label}: {f.result.chunk_text[:80]}"
            )

        assert len(fused) > 0
    finally:
        session.close()
