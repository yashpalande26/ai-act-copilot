from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session, aliased

from app.db.models import Chunk, Provision
from app.ingestion.chunker import citation_label
from app.ingestion.embedder import DIMENSIONS, MODEL, _get_client


class SearchResult(BaseModel):
    chunk_id: int
    citation_id: str
    citation_label: str
    chunk_text: str
    similarity: float
    article_heading: str | None


def embed_query(text: str) -> list[float]:
    client = _get_client()
    response = client.embeddings.create(
        model=MODEL, input=[text], dimensions=DIMENSIONS
    )
    return response.data[0].embedding


def vector_search(
    session: Session,
    query: str,
    corpus_version_id: int,
    top_k: int = 5,
    min_similarity: float = 0.0,
) -> list[SearchResult]:
    query_embedding = embed_query(query)
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")

    Ancestor = aliased(Provision)
    stmt = (
        select(Chunk, Provision, Ancestor, distance)
        .join(Provision, Chunk.provision_id == Provision.id)
        .outerjoin(Ancestor, Chunk.parent_provision_id == Ancestor.id)
        .where(Chunk.corpus_version_id == corpus_version_id)
        .order_by(distance.asc())
        .limit(top_k)
    )

    results: list[SearchResult] = []
    for chunk, provision, ancestor, dist in session.execute(stmt).all():
        similarity = 1 - dist
        if similarity < min_similarity:
            continue
        results.append(
            SearchResult(
                chunk_id=chunk.id,
                citation_id=provision.citation_id,
                citation_label=citation_label(provision.citation_id),
                chunk_text=chunk.chunk_text,
                similarity=similarity,
                article_heading=ancestor.heading if ancestor is not None else None,
            )
        )
    return results[:top_k]


_KEYWORD_SEARCH_SQL = text(
    """
    SELECT
        c.id AS chunk_id,
        c.chunk_text,
        p.citation_id,
        ap.heading AS article_heading,
        ts_rank_cd(
            to_tsvector('english', c.chunk_text),
            websearch_to_tsquery('english', :query)
        ) AS rank_score
    FROM chunk c
    JOIN provision p ON p.id = c.provision_id
    LEFT JOIN provision ap ON ap.id = c.parent_provision_id
    WHERE c.corpus_version_id = :corpus_version_id
      AND to_tsvector('english', c.chunk_text) @@ websearch_to_tsquery('english', :query)
    ORDER BY rank_score DESC
    LIMIT :top_k
    """
)


def keyword_search(
    session: Session,
    query: str,
    corpus_version_id: int,
    top_k: int = 10,
    threshold: float = 0.1,
) -> list[SearchResult]:
    """Full-text search over chunk_text using Postgres websearch_to_tsquery,
    ranked by ts_rank_cd, scoped to one corpus_version. Returns SearchResult
    (same shape vector_search returns), with `similarity` holding the
    ts_rank_cd score rather than a cosine similarity - both are "higher is
    better" relevance scores, just not directly comparable in magnitude,
    which is exactly why RRF fuses by *rank*, not by raw score.
    """
    rows = session.execute(
        _KEYWORD_SEARCH_SQL,
        {"query": query, "corpus_version_id": corpus_version_id, "top_k": top_k},
    ).all()

    results: list[SearchResult] = []
    for row in rows:
        if row.rank_score < threshold:
            continue
        results.append(
            SearchResult(
                chunk_id=row.chunk_id,
                citation_id=row.citation_id,
                citation_label=citation_label(row.citation_id),
                chunk_text=row.chunk_text,
                similarity=row.rank_score,
                article_heading=row.article_heading,
            )
        )
    return results[:top_k]


class FusedResult(BaseModel):
    """One fused hybrid-search result: the underlying SearchResult plus the
    fusion bookkeeping. Kept separate from SearchResult.similarity (a cosine
    similarity) rather than overloading that field with an RRF score, which
    is a different kind of number (typically ~0.01-0.03) - conflating them
    would silently corrupt anything downstream that assumes `similarity` is
    a cosine value.
    """

    result: SearchResult
    rrf_score: float
    vector_rank: int | None  # 0-indexed rank in vector_results, or None if absent
    lexical_rank: int | None  # 0-indexed rank in lexical_results, or None if absent


def rrf_rank_and_fuse(
    vector_results: list[SearchResult],
    lexical_results: list[SearchResult],
    vector_weight: float = 0.7,
    lexical_weight: float = 0.3,
    k: int = 60,
    top_k: int = 10,
) -> list[FusedResult]:
    """Weighted Reciprocal Rank Fusion. For each chunk_id, score =
    vector_weight/(k + rank_v + 1) + lexical_weight/(k + rank_l + 1), using
    only the terms for lists the chunk actually appears in (absent = that
    term is 0, not a fallback rank). Sorted by score descending, top_k kept.
    """
    vector_ranks = {r.chunk_id: i for i, r in enumerate(vector_results)}
    lexical_ranks = {r.chunk_id: i for i, r in enumerate(lexical_results)}

    by_chunk_id: dict[int, SearchResult] = {r.chunk_id: r for r in vector_results}
    for r in lexical_results:
        by_chunk_id.setdefault(r.chunk_id, r)

    fused: list[FusedResult] = []
    for chunk_id, result in by_chunk_id.items():
        rank_v = vector_ranks.get(chunk_id)
        rank_l = lexical_ranks.get(chunk_id)
        score = 0.0
        if rank_v is not None:
            score += vector_weight * (1 / (k + rank_v + 1))
        if rank_l is not None:
            score += lexical_weight * (1 / (k + rank_l + 1))
        fused.append(
            FusedResult(
                result=result, rrf_score=score, vector_rank=rank_v, lexical_rank=rank_l
            )
        )

    fused.sort(key=lambda f: f.rrf_score, reverse=True)
    return fused[:top_k]
