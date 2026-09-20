import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.db.models import Chunk, CorpusVersion
from app.db.session import SessionLocal
from app.retrieval.bm25_index import build_index, index_dir


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

        # Fairness guard: BM25 must index exactly the universe vector_search can
        # reach, or the vector-vs-BM25 comparison is measuring different
        # candidate sets rather than different rankers.
        total = session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.corpus_version_id == latest.id)
        ).scalar()
        vector_searchable = session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(
                Chunk.corpus_version_id == latest.id,
                Chunk.embedding.isnot(None),
            )
        ).scalar()

        manifest = build_index(session, latest.id)

        target = index_dir(latest.id)
        size_kb = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1024

        print(f"corpus_version:            {latest.id}")
        print(f"chunks (total):            {total}")
        print(f"chunks vector-searchable:  {vector_searchable}")
        print(f"documents indexed:         {manifest['doc_count']}")
        print(
            f"candidate sets match:      {manifest['doc_count'] == vector_searchable}"
        )
        if total != vector_searchable:
            print(
                f"  NOTE: {total - vector_searchable} chunk(s) have no embedding and "
                "are unreachable by vector_search; they are excluded from the BM25 "
                "index too, so both legs stay comparable.",
                file=sys.stderr,
            )
        print(f"index dir:                 {target}")
        print(f"index size:                {size_kb:.1f} KiB")
    finally:
        session.close()


if __name__ == "__main__":
    main()
