import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import CorpusVersion
from app.db.session import SessionLocal
from app.retrieval.search import vector_search


def main() -> None:
    if len(sys.argv) < 2:
        print(
            'Usage: python -m scripts.search_cli "your question here" [top_k]',
            file=sys.stderr,
        )
        sys.exit(1)

    query = sys.argv[1]
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 5

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

        results = vector_search(session, query, latest.id, top_k=top_k)
        for rank, result in enumerate(results, start=1):
            print(f"{rank}. [{result.similarity:.3f}] {result.citation_label}")
            print(f"   {result.chunk_text[:200]}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
