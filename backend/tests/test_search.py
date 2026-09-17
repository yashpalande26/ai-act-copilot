from unittest.mock import MagicMock

from app.db.models import Chunk, Provision
from app.retrieval import search as search_module


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
