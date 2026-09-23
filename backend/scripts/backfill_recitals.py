"""Add the recitals of the ORIGINAL Official Journal act to the live corpus
(ADR-32, 23 Sep 2026). The consolidated text (02024R1689-20260727) drops the
preamble; the source here is backend/data/aiact_32024R1689.html, fetched by
hand from EUR-Lex (the WAF blocks scripted fetches, ADR-001).

    python scripts/backfill_recitals.py            # dry run: prints the plan and the source hash, writes nothing
    python scripts/backfill_recitals.py --execute  # inserts 180 rows, adds chunks, embeds them, rebuilds BM25

The rows join the latest corpus_version (the retriever filters on one
version); each row's eid records the source document (32024R1689:rct_N) and
the ADR records the file's SHA-256 and OJ date. Refuses if any rec_ row exists.
"""

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.db.models import Chunk, CorpusVersion, Provision
from app.db.session import SessionLocal
from app.ingestion.chunker import build_missing_chunks
from app.ingestion.embedder import embed_corpus
from app.ingestion.parser import parse_recitals
from app.retrieval.bm25_index import build_index

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "data" / "aiact_32024R1689.html"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    raw = HTML.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    parsed = parse_recitals(raw.decode("utf-8"))
    print(f"source {HTML.name}  bytes {len(raw)}  sha256 {digest}")
    print(f"recitals parsed: {len(parsed)}  first: {parsed[0].text_content[:80]!r}")
    print(
        f"  rec_58: {next(p.text_content for p in parsed if p.citation_id == 'rec_58')[:100]!r}"
    )
    print(f"  rec_180: {parsed[-1].text_content[:100]!r}")
    session = SessionLocal()
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        existing = session.execute(
            select(func.count())
            .select_from(Provision)
            .where(
                Provision.corpus_version_id == cv.id, Provision.unit_type == "recital"
            )
        ).scalar()
        before = session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.corpus_version_id == cv.id)
        ).scalar()
        print(
            f"corpus_version {cv.id}  existing recital rows: {existing}  chunks before: {before}"
        )
        if existing:
            raise SystemExit("recitals already present; refusing to insert twice")
        if not args.execute:
            print("\ndry run: nothing written. Re-run with --execute.")
            return
        for p in parsed:
            session.add(
                Provision(
                    corpus_version_id=cv.id,
                    citation_id=p.citation_id,
                    eid=p.eid,
                    parent_id=None,
                    unit_type=p.unit_type,
                    number=p.number,
                    heading=p.heading,
                    text_content=p.text_content,
                    amendment_marker=None,
                    ordinal=p.ordinal,
                )
            )
        session.flush()
        added = build_missing_chunks(session, cv.id)
        session.commit()
        print(f"\nrows inserted: {len(parsed)}  chunks added: {added}")
        result = embed_corpus(session, cv.id)
        print(
            f"embedded: {result['chunks_embedded']} chunks, {result['total_tokens']} tokens"
        )
        manifest = build_index(session, cv.id)
        print(f"bm25 rebuilt: {manifest['doc_count']} documents")
    finally:
        session.close()


if __name__ == "__main__":
    main()
