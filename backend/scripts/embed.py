import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.db.models import Chunk, CorpusVersion
from app.db.session import SessionLocal
from app.ingestion.embedder import embed_corpus

COST_PER_MILLION_TOKENS = 0.13  # text-embedding-3-large


def main() -> None:
    session = SessionLocal()
    try:
        latest = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        if latest is None:
            print("No corpus_version found. Run ingest.py first.", file=sys.stderr)
            sys.exit(1)

        result = embed_corpus(session, latest.id)
        cost = result["total_tokens"] / 1_000_000 * COST_PER_MILLION_TOKENS

        print(f"Chunks embedded: {result['chunks_embedded']}")
        print(f"Batches: {result['batches']}")
        print(f"Total tokens: {result['total_tokens']}")
        print(f"Estimated cost: ${cost:.4f}")

        remaining = session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.corpus_version_id == latest.id, Chunk.embedding.is_(None))
        ).scalar_one()
        print(f"Chunks remaining with NULL embedding: {remaining}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
