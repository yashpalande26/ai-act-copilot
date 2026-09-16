import sys
from datetime import date
from pathlib import Path

# Make `app` importable regardless of how this script is invoked (it isn't
# a package member, so plain `python .../ingest.py` would only put its own
# directory on sys.path, not backend/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import CorpusVersion
from app.db.session import SessionLocal
from app.ingestion.loader import build_corpus, load_corpus, validate_corpus

HTML_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "aiact_02024R1689-20260727.html"
)
CELEX = "02024R1689-20260727"
CONSOLIDATED_DATE = date(2026, 7, 27)
VALID_FROM = date(2026, 7, 27)
SOURCE_URL = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02024R1689-20260727"
)


def main() -> None:
    if not HTML_PATH.exists():
        print(f"Not found: {HTML_PATH}. Run fetch_corpus.py first.", file=sys.stderr)
        sys.exit(1)

    html = HTML_PATH.read_text(encoding="utf-8")
    corpus_metadata, provisions = build_corpus(
        html,
        celex=CELEX,
        consolidated_date=CONSOLIDATED_DATE,
        valid_from=VALID_FROM,
        source_url=SOURCE_URL,
    )
    validate_corpus(provisions)

    article_count = sum(1 for p in provisions if p.unit_type == "article")
    print(f"Articles parsed: {article_count}")
    print(f"Total provisions: {len(provisions)}")

    session = SessionLocal()
    try:
        already_existed = (
            session.execute(
                select(CorpusVersion.id).where(
                    CorpusVersion.content_hash == corpus_metadata["content_hash"]
                )
            ).scalar_one_or_none()
            is not None
        )
        corpus_version_id = load_corpus(session, corpus_metadata, provisions)
        if already_existed:
            print(f"Already ingested (corpus_version id={corpus_version_id})")
        else:
            print(f"Loaded corpus_version id={corpus_version_id}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
