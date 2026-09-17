import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import CorpusVersion
from app.db.session import SessionLocal
from app.ingestion.chunker import build_chunks


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

        count = build_chunks(session, latest.id)
        print(f"Built {count} chunks for corpus_version id={latest.id}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
