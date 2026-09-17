import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

MODEL = "text-embedding-3-large"
DIMENSIONS = 1536


def _get_client() -> OpenAI:
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def embed_corpus(
    session: Session, corpus_version_id: int, batch_size: int = 100
) -> dict:
    chunks = (
        session.execute(
            select(Chunk).where(
                Chunk.corpus_version_id == corpus_version_id,
                Chunk.embedding.is_(None),
            )
        )
        .scalars()
        .all()
    )

    client = _get_client()
    chunks_embedded = 0
    batches = 0
    total_tokens = 0

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        batches += 1
        try:
            response = client.embeddings.create(
                model=MODEL,
                input=[c.index_text for c in batch],
                dimensions=DIMENSIONS,
            )
        except Exception:
            print(
                f"Batch {batches} failed (chunk ids {[c.id for c in batch]})",
                file=sys.stderr,
            )
            raise

        for chunk, item in zip(batch, response.data):
            chunk.embedding = item.embedding

        total_tokens += response.usage.total_tokens
        chunks_embedded += len(batch)
        session.commit()

    return {
        "chunks_embedded": chunks_embedded,
        "batches": batches,
        "total_tokens": total_tokens,
    }
