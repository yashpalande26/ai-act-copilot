"""Add one annex to the live corpus without re-ingesting (23 Sep 2026).

    python scripts/backfill_annex.py anx_I            # dry run: prints the rows, writes nothing
    python scripts/backfill_annex.py anx_I --execute  # inserts rows, adds chunks, embeds them, rebuilds BM25 and the structure map

Refuses when the source file's hash differs from corpus_version.content_hash
or when the annex already has rows. Rows are inserted with their parent
chain and ordinals exactly as load_corpus would; deleted items are kept as
rows with empty text and their marker and get no chunk. Only chunks with a
NULL embedding are embedded; the BM25 index is rebuilt over all embedded
chunks (bm25s has no append; a local file). The structure map is rebuilt so
the section ids are known to the retriever.
"""

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.db.models import Chunk, CorpusVersion, Provision
from app.db.session import SessionLocal
from app.ingestion.chunker import build_missing_chunks, citation_label
from app.ingestion.embedder import embed_corpus
from app.ingestion.parser import (
    is_sectioned_annex,
    parse_annex,
    parse_sectioned_annex,
    split_document,
)
from app.retrieval.bm25_index import build_index

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "data" / "aiact_02024R1689-20260727.html"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("annex", help="annex id, e.g. anx_I")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    html = HTML.read_text(encoding="utf-8")
    session = SessionLocal()
    try:
        cv = (
            session.execute(select(CorpusVersion).order_by(CorpusVersion.id.desc()))
            .scalars()
            .first()
        )
        digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
        if digest != cv.content_hash:
            raise SystemExit(
                "source file hash differs from the corpus_version hash; refusing"
            )
        _, annex_blocks = split_document(html)
        block = next(
            (b for b in annex_blocks if re.search(rf'id="{re.escape(args.annex)}"', b)),
            None,
        )
        if block is None:
            raise SystemExit(f"{args.annex} not found in the source")
        parsed = (
            parse_sectioned_annex(block)
            if is_sectioned_annex(block)
            else parse_annex(block)
        )
        existing = session.execute(
            select(func.count())
            .select_from(Provision)
            .where(
                Provision.corpus_version_id == cv.id,
                (Provision.citation_id == args.annex)
                | Provision.citation_id.like(f"{args.annex}.%"),
            )
        ).scalar()
        before_chunks = session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.corpus_version_id == cv.id)
        ).scalar()
        print(
            f"corpus_version {cv.id}  existing {args.annex} rows: {existing}  chunks before: {before_chunks}"
        )
        chunkable = sum(
            1 for p in parsed if p.unit_type == "annex_point" and p.text_content
        )
        print(f"rows to insert: {len(parsed)}  (chunkable: {chunkable})")
        for p in parsed:
            flag = " DELETED" if p.deleted else ""
            print(
                f"  {p.citation_id:<20} {p.unit_type:<14} m={p.amendment_marker or '-':<3}{flag:<8} {citation_label(p.citation_id):<28} {p.text_content[:60]!r}"
            )
        if existing:
            raise SystemExit("annex already present; refusing to insert twice")
        if not args.execute:
            print("\ndry run: nothing written. Re-run with --execute.")
            return
        by_cid: dict[str, Provision] = {}
        for p in parsed:
            parent = by_cid.get(p.parent_citation_id) if p.parent_citation_id else None
            row = Provision(
                corpus_version_id=cv.id,
                citation_id=p.citation_id,
                eid=p.eid,
                parent_id=parent.id if parent is not None else None,
                unit_type=p.unit_type,
                number=p.number,
                heading=p.heading,
                text_content=p.text_content,
                amendment_marker=p.amendment_marker,
                ordinal=p.ordinal,
            )
            session.add(row)
            session.flush()
            by_cid[p.citation_id] = row
        added = build_missing_chunks(session, cv.id)
        session.commit()
        print(f"\nrows inserted: {len(parsed)}  chunks added: {added}")
        result = embed_corpus(session, cv.id)
        print(
            f"embedded: {result['chunks_embedded']} chunks, {result['total_tokens']} tokens"
        )
        manifest = build_index(session, cv.id)
        print(f"bm25 rebuilt: {manifest['doc_count']} documents")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_structure.py")], check=True
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
