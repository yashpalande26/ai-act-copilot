from unittest.mock import MagicMock

from app.db.models import Chunk


class _FakeItem:
    def __init__(self, embedding):
        self.embedding = embedding


class _FakeUsage:
    def __init__(self, total_tokens):
        self.total_tokens = total_tokens


class _FakeResponse:
    def __init__(self, embeddings, total_tokens):
        self.data = [_FakeItem(e) for e in embeddings]
        self.usage = _FakeUsage(total_tokens)


def _make_chunks(n: int) -> list[Chunk]:
    return [
        Chunk(id=i, index_text=f"text {i}", embedding=None) for i in range(1, n + 1)
    ]


def _make_session(chunks: list[Chunk]) -> MagicMock:
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = chunks
    return session


def test_batching_splits_into_ceil_n_over_batch_size_calls(monkeypatch):
    from app.ingestion import embedder

    chunks = _make_chunks(25)
    session = _make_session(chunks)

    fake_client = MagicMock()
    fake_client.embeddings.create.side_effect = [
        _FakeResponse([[0.1]] * 10, total_tokens=100),
        _FakeResponse([[0.2]] * 10, total_tokens=100),
        _FakeResponse([[0.3]] * 5, total_tokens=50),
    ]
    monkeypatch.setattr(embedder, "_get_client", lambda: fake_client)

    result = embedder.embed_corpus(session, corpus_version_id=1, batch_size=10)

    assert fake_client.embeddings.create.call_count == 3  # ceil(25/10)
    assert result["batches"] == 3
    assert result["chunks_embedded"] == 25


def test_vectors_mapped_to_correct_chunks(monkeypatch):
    from app.ingestion import embedder

    chunks = _make_chunks(2)
    session = _make_session(chunks)

    fake_client = MagicMock()
    fake_client.embeddings.create.return_value = _FakeResponse(
        [[1.0, 2.0], [3.0, 4.0]], total_tokens=42
    )
    monkeypatch.setattr(embedder, "_get_client", lambda: fake_client)

    embedder.embed_corpus(session, corpus_version_id=1, batch_size=10)

    assert chunks[0].embedding == [1.0, 2.0]
    assert chunks[1].embedding == [3.0, 4.0]


def test_token_counting_sums_across_batches(monkeypatch):
    from app.ingestion import embedder

    chunks = _make_chunks(15)
    session = _make_session(chunks)

    fake_client = MagicMock()
    fake_client.embeddings.create.side_effect = [
        _FakeResponse([[0.0]] * 10, total_tokens=100),
        _FakeResponse([[0.0]] * 5, total_tokens=40),
    ]
    monkeypatch.setattr(embedder, "_get_client", lambda: fake_client)

    result = embedder.embed_corpus(session, corpus_version_id=1, batch_size=10)

    assert result["total_tokens"] == 140
