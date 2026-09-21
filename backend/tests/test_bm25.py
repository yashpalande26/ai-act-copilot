import json
import os
from unittest.mock import MagicMock

import pytest

from app.retrieval import bm25_index
from app.retrieval.bm25_index import (
    PROTECTED_TERMS,
    StaleIndexError,
    make_stemmer,
    tokenize_corpus,
    tokenize_query,
)


@pytest.fixture(autouse=True)
def _clear_index_cache():
    bm25_index._CACHE.clear()
    yield
    bm25_index._CACHE.clear()


# --- tokenization -------------------------------------------------------


def test_query_and_document_tokenization_agree():
    """The single invariant that silently breaks retrieval if violated: a
    string must produce the same tokens as a document and as a query."""
    text = "Providers of high-risk AI systems shall ensure compliance"

    doc_tokens = tokenize_corpus([text])
    doc_vocab = {t for t in doc_tokens.vocab}
    query_tokens = set(tokenize_query(text)[0])

    assert query_tokens
    assert query_tokens <= doc_vocab


def test_protected_terms_bypass_the_stemmer():
    stem = make_stemmer()
    # 'systemic' must NOT collapse into the 'system' stem: systemic risk is a
    # general-purpose-model concept, unrelated to an AI system.
    assert stem(["systemic"]) == ["systemic"]
    assert stem(["system"]) != ["systemic"]
    assert stem(["systems"]) == stem(["system"])  # plain plural folding is fine
    # singular and plural of a protected role stay together
    assert stem(["provider"]) == stem(["providers"]) == ["provider"]
    assert stem(["deployer"]) == stem(["deployers"]) == ["deployer"]


def test_unprotected_words_are_still_stemmed():
    stem = make_stemmer()
    assert stem(["obligations"]) == stem(["obligation"])
    assert "importer" not in PROTECTED_TERMS  # no contamination, no protection


# --- build / load roundtrip --------------------------------------------


def _build_tiny_index(tmp_path, monkeypatch, corpus_version_id=7):
    monkeypatch.setattr(bm25_index, "INDEX_ROOT", tmp_path / "bm25_index")
    rows = [
        (
            101,
            "Providers of high-risk AI systems shall establish a risk management system.",
        ),
        (102, "Systemic risk of general-purpose AI models shall be assessed."),
        (103, "The notified body shall issue a certificate of conformity."),
    ]
    monkeypatch.setattr(bm25_index, "fetch_indexable_chunks", lambda session, cv: rows)
    manifest = bm25_index.build_index(MagicMock(), corpus_version_id)
    return manifest, rows


def test_build_and_load_roundtrip(tmp_path, monkeypatch):
    manifest, _rows = _build_tiny_index(tmp_path, monkeypatch)

    assert manifest["doc_count"] == 3
    assert manifest["chunk_ids"] == [101, 102, 103]

    bm25_index._CACHE.clear()
    loaded = bm25_index.load_index(7)

    assert loaded is not None
    assert loaded.chunk_ids == [101, 102, 103]
    assert loaded.tokenizer_config["stemmer"] == "snowball-english"


def test_load_index_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(bm25_index, "INDEX_ROOT", tmp_path / "nothing_here")
    assert bm25_index.load_index(1) is None


def test_load_index_raises_on_corpus_version_mismatch(tmp_path, monkeypatch):
    _build_tiny_index(tmp_path, monkeypatch, corpus_version_id=7)

    # Rewrite the manifest to claim a different corpus_version, as a stale
    # index would: its chunk_id mapping points at the wrong rows.
    manifest_path = bm25_index.index_dir(7) / "manifest.json"
    data = json.loads(manifest_path.read_text())
    data["corpus_version_id"] = 999
    manifest_path.write_text(json.dumps(data))
    bm25_index._CACHE.clear()

    with pytest.raises(StaleIndexError):
        bm25_index.load_index(7)


# --- bm25_search hydration ---------------------------------------------


def test_bm25_search_returns_empty_when_no_index(tmp_path, monkeypatch):
    monkeypatch.setattr(bm25_index, "INDEX_ROOT", tmp_path / "absent")
    from app.retrieval import search as search_module

    session = MagicMock()
    results = search_module.bm25_search(session, "anything", corpus_version_id=1)

    assert results == []
    session.execute.assert_not_called()


def test_bm25_search_preserves_bm25_order_not_db_order(tmp_path, monkeypatch):
    """WHERE id IN (...) returns rows in arbitrary order - results must be
    re-sorted into BM25 rank order, or every rank metric downstream is wrong."""
    from app.db.models import Chunk, Provision
    from app.retrieval import search as search_module

    _build_tiny_index(tmp_path, monkeypatch)

    def _row(chunk_id, citation_id, text):
        chunk = Chunk(chunk_text=text)
        chunk.id = chunk_id
        provision = Provision(citation_id=citation_id)
        return (chunk, provision, None)

    # Deliberately shuffled relative to any plausible BM25 ranking.
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        _row(
            103, "art_3", "The notified body shall issue a certificate of conformity."
        ),
        _row(
            101,
            "art_1",
            "Providers of high-risk AI systems shall establish a risk management system.",
        ),
        _row(
            102,
            "art_2",
            "Systemic risk of general-purpose AI models shall be assessed.",
        ),
    ]

    results = search_module.bm25_search(
        session, "notified body certificate", corpus_version_id=7
    )

    assert results, "expected BM25 to match the notified-body document"
    # The notified-body chunk is the lexical match, so it must come first
    # regardless of the order the DB handed rows back.
    assert results[0].chunk_id == 103
    assert results[0].citation_id == "art_3"
    # scores are BM25, documented as going in .similarity
    assert results[0].similarity > 0
    # ordering is strictly descending by score
    assert [r.similarity for r in results] == sorted(
        (r.similarity for r in results), reverse=True
    )


# --- integration --------------------------------------------------------


@pytest.mark.live
def test_bm25_search_against_real_corpus():
    if not os.environ.get("DATABASE_URL") or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("DATABASE_URL / OPENAI_API_KEY not configured")

    from sqlalchemy import select

    from app.db.models import CorpusVersion
    from app.db.session import SessionLocal
    from app.retrieval.search import bm25_search

    session = SessionLocal()
    try:
        latest = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        if latest is None or bm25_index.load_index(latest.id) is None:
            pytest.skip("no corpus_version or no bm25 index built")

        results = bm25_search(
            session, "notified body conformity assessment", latest.id, top_k=5
        )
        assert results
        assert all(r.similarity > 0 for r in results)
        assert len({r.chunk_id for r in results}) == len(results)
    finally:
        session.close()
