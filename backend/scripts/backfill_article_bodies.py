"""Backfill the bodies of single-paragraph articles into the live corpus
(23 Sep 2026). The corpus audit found eight articles (32, 39, 85, 87, 94,
102, 103, 104) whose body is a bare paragraph the parser dropped: only the
heading was stored, so the text was in no provision row and un-retrievable.

    python scripts/backfill_article_bodies.py            # dry run: prints the plan, writes nothing
    python scripts/backfill_article_bodies.py --execute  # updates rows, adds chunks, embeds them, rebuilds BM25

What --execute does, in order, against the latest corpus_version:
  1. re-parse the cached source HTML with the fixed parser; for every
     article row whose stored text is its heading, that has no children, and
     whose parsed body differs, set text_content to the body (one UPDATE per
     article, one transaction);
  2. app.ingestion.chunker.build_missing_chunks: chunks only for leaves that
     have none (the existing 1,128 chunks and their embeddings are untouched);
  3. app.ingestion.embedder.embed_corpus: embeds only chunks whose embedding
     is NULL (the new ones);
  4. app.retrieval.bm25_index.build_index: the sparse index is rebuilt over
     all embedded chunks, because bm25s has no append; this is a local file,
     not an API spend.
The source file's hash is checked against corpus_version.content_hash first:
a different file means a different text and this script refuses.
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
from app.ingestion.parser import parse_article, split_document
from app.retrieval.bm25_index import build_index

HTML = Path(__file__).resolve().parents[1] / "data" / "aiact_02024R1689-20260727.html"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
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
                f"source file hash {digest[:12]} != corpus_version {cv.id} hash {cv.content_hash[:12]}; refusing"
            )
        article_blocks, _ = split_document(html)
        parsed = {}
        for block in article_blocks:
            provs = parse_article(block)
            parsed[provs[0].citation_id] = (provs[0], len(provs) - 1)
        rows = (
            session.execute(
                select(Provision).where(
                    Provision.corpus_version_id == cv.id,
                    Provision.unit_type == "article",
                )
            )
            .scalars()
            .all()
        )
        parents = set(
            session.execute(
                select(Provision.parent_id).where(
                    Provision.corpus_version_id == cv.id,
                    Provision.parent_id.isnot(None),
                )
            )
            .scalars()
            .all()
        )
        plan = []
        for row in rows:
            p, n_children = parsed.get(row.citation_id, (None, None))
            if p is None:
                continue
            stored_is_heading = (row.text_content or "").strip() == (
                row.heading or ""
            ).strip()
            body_differs = p.text_content.strip() != (row.text_content or "").strip()
            if (
                stored_is_heading
                and row.id not in parents
                and n_children == 0
                and body_differs
            ):
                plan.append((row, p.text_content))
        before_chunks = session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.corpus_version_id == cv.id)
        ).scalar()
        print(f"corpus_version {cv.id} ({cv.celex})  chunks before: {before_chunks}")
        print(f"articles to backfill: {len(plan)}")
        for row, body in plan:
            print(f"  {row.citation_id:<9} {len(body):>5} chars  {body[:90]!r}")
        if not args.execute:
            print("\ndry run: nothing written. Re-run with --execute.")
            return
        for row, body in plan:
            row.text_content = body
        session.flush()
        added = build_missing_chunks(session, cv.id)
        session.commit()
        print(f"\nrows updated: {len(plan)}  chunks added: {added}")
        result = embed_corpus(session, cv.id)
        print(
            f"embedded: {result['chunks_embedded']} chunks, {result['total_tokens']} tokens (only NULL embeddings)"
        )
        manifest = build_index(session, cv.id)
        print(f"bm25 rebuilt: {manifest['doc_count']} documents")
        after_chunks = session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.corpus_version_id == cv.id)
        ).scalar()
        unembedded = session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.corpus_version_id == cv.id, Chunk.embedding.is_(None))
        ).scalar()
        print(f"chunks after: {after_chunks}  unembedded: {unembedded}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
