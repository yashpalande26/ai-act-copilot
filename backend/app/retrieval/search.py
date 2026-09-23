import re

from pydantic import BaseModel
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session, aliased

from app.db.models import Chunk, Provision
from app.ingestion.chunker import citation_label
from app.ingestion.embedder import DIMENSIONS, MODEL, _get_client
from app.retrieval.bm25_index import load_index, tokenize_query


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
    exclude_recitals: bool = False,
) -> list[SearchResult]:
    query_embedding = embed_query(query)
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")

    Ancestor = aliased(Provision)
    stmt = (
        select(Chunk, Provision, Ancestor, distance)
        .join(Provision, Chunk.provision_id == Provision.id)
        .outerjoin(Ancestor, Chunk.parent_provision_id == Ancestor.id)
        .where(Chunk.corpus_version_id == corpus_version_id)
    )
    if exclude_recitals:
        # ADR-33: recitals reach the context through the recital map only.
        stmt = stmt.where(Provision.unit_type != "recital")
    stmt = stmt.order_by(distance.asc()).limit(top_k)

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


def _citation_sort_key(citation_id: str) -> tuple:
    """Natural order of a provision's parts: art_9 < art_9.par_1 < art_9.par_2
    < art_9.par_10; letters after numbers."""
    key = []
    for seg in citation_id.split("."):
        m = re.match(r"([a-z]+)_(\d+)?([a-z_()]*)", seg)
        if m:
            key.append((m.group(1), int(m.group(2) or 0), m.group(3) or ""))
        else:
            key.append((seg, 0, ""))
    return tuple(key)


def fetch_provision_chunks(
    session: Session, corpus_version_id: int, roots: list[str]
) -> dict[str, list[SearchResult]]:
    """Every chunk under each provision root ("art_9" covers art_9 and
    art_9.*), in natural citation order, as SearchResults shaped exactly like
    vector_search's (similarity 0.0: these were not scored, they were
    resolved). Used by the cross-reference expansion; no embedding call."""
    if not roots:
        return {}
    Ancestor = aliased(Provision)
    conds = [
        (Provision.citation_id == r) | Provision.citation_id.like(f"{r}.%")
        for r in roots
    ]
    stmt = (
        select(Chunk, Provision, Ancestor)
        .join(Provision, Chunk.provision_id == Provision.id)
        .outerjoin(Ancestor, Chunk.parent_provision_id == Ancestor.id)
        .where(Chunk.corpus_version_id == corpus_version_id, or_(*conds))
    )
    by_root: dict[str, list[SearchResult]] = {r: [] for r in roots}
    for chunk, provision, ancestor in session.execute(stmt).all():
        cid = provision.citation_id
        root = next(r for r in roots if cid == r or cid.startswith(r + "."))
        by_root[root].append(
            SearchResult(
                chunk_id=chunk.id,
                citation_id=cid,
                citation_label=citation_label(cid),
                chunk_text=chunk.chunk_text,
                similarity=0.0,
                article_heading=ancestor.heading if ancestor is not None else None,
            )
        )
    for rows in by_root.values():
        rows.sort(key=lambda x: _citation_sort_key(x.citation_id))
    return by_root


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


def bm25_search(
    session: Session,
    query: str,
    corpus_version_id: int,
    top_k: int = 10,
    exclude_recitals: bool = False,
) -> list[SearchResult]:
    """BM25 retrieval over the on-disk bm25s index for this corpus_version.
    With exclude_recitals (ADR-33) recital chunks are dropped after ranking
    and the leg is deepened so it still returns up to top_k operative
    chunks: the same candidate universe the vector leg draws from.

    Returns SearchResult (the same shape vector_search returns), with
    `similarity` holding the BM25 score rather than a cosine similarity - both
    are "higher is better" relevance scores but not comparable in magnitude,
    which is exactly why RRF fuses by *rank*, not by raw score. Same convention
    keyword_search uses for ts_rank_cd.

    Returns [] when no index has been built (callers then degrade to
    vector-only, as they already do for an empty lexical leg); raises
    StaleIndexError when an index exists but belongs to another
    corpus_version. See bm25_index.StaleIndexError for why that asymmetry.
    """
    loaded = load_index(corpus_version_id)
    if loaded is None:
        return []

    query_tokens = tokenize_query(query)
    depth = min(top_k * 3 if exclude_recitals else top_k, len(loaded.chunk_ids))
    doc_indices, scores = loaded.retriever.retrieve(
        query_tokens, k=depth, show_progress=False
    )

    # retrieve() returns one row per query; we always pass exactly one.
    ranked: list[tuple[int, float]] = [
        (loaded.chunk_ids[int(doc_idx)], float(score))
        for doc_idx, score in zip(doc_indices[0], scores[0], strict=True)
    ]
    if not ranked:
        return []

    score_by_chunk_id = dict(ranked)
    Ancestor = aliased(Provision)
    stmt = (
        select(Chunk, Provision, Ancestor)
        .join(Provision, Chunk.provision_id == Provision.id)
        .outerjoin(Ancestor, Chunk.parent_provision_id == Ancestor.id)
        .where(Chunk.id.in_(score_by_chunk_id))
    )
    if exclude_recitals:
        stmt = stmt.where(Provision.unit_type != "recital")
    hydrated = {
        chunk.id: SearchResult(
            chunk_id=chunk.id,
            citation_id=provision.citation_id,
            citation_label=citation_label(provision.citation_id),
            chunk_text=chunk.chunk_text,
            similarity=score_by_chunk_id[chunk.id],
            article_heading=ancestor.heading if ancestor is not None else None,
        )
        for chunk, provision, ancestor in session.execute(stmt).all()
    }

    # WHERE id IN (...) returns rows in ARBITRARY order, so rebuild the BM25
    # ranking explicitly - relying on DB order here would silently reorder
    # results and corrupt every rank-based metric downstream.
    # Excluding recitals ranked deeper (depth above); the leg is still cut to
    # top_k so it is the same length as the vector leg it is fused with.
    return [hydrated[cid] for cid, _ in ranked if cid in hydrated][:top_k]


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
