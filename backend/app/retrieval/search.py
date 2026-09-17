from pydantic import BaseModel
from sqlalchemy import select
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
