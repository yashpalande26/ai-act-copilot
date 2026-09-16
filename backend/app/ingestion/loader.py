import hashlib
import re
from collections import Counter
from datetime import date

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CorpusVersion, Provision
from app.ingestion.models import ParsedProvision
from app.ingestion.parser import _clean_text, parse_annex, parse_article, split_document

# These annexes use a different top-level structure - numbered sections via
# <p class="title-gr-seq-level-1"> (Annex VII additionally has decimal
# sub-numbering, e.g. "3.1.") - that parse_annex doesn't model yet; it only
# understands Annex III's grid-container/lettered-point convention. Loading
# them today would misattribute their points to the annex root. Excluded
# until that's built ("Step B").
UNSUPPORTED_ANNEXES = {"anx_I", "anx_VII", "anx_VIII", "anx_X", "anx_XI", "anx_XIV"}


def build_corpus(
    html: str,
    *,
    celex: str,
    consolidated_date: date,
    valid_from: date,
    source_url: str,
) -> tuple[dict, list[ParsedProvision]]:
    article_blocks, annex_blocks = split_document(html)

    provisions: list[ParsedProvision] = []
    for block in article_blocks:
        provisions.extend(parse_article(block))

    skipped_annexes = []
    for block in annex_blocks:
        match = re.search(r'id="(anx_[^"]+)"', block)
        annex_id = match.group(1) if match else "?"
        if annex_id in UNSUPPORTED_ANNEXES:
            skipped_annexes.append(annex_id)
            continue
        provisions.extend(parse_annex(block))

    if skipped_annexes:
        print(
            f"Skipping unsupported annexes (Step B pending): {sorted(skipped_annexes)}"
        )

    title_tag = BeautifulSoup(html, "lxml").find("title")
    title = _clean_text(title_tag.get_text()) if title_tag else celex

    corpus_metadata = {
        "celex": celex,
        "title": title,
        "consolidated_date": consolidated_date,
        "valid_from": valid_from,
        "source_url": source_url,
        "content_hash": hashlib.sha256(html.encode("utf-8")).hexdigest(),
    }
    return corpus_metadata, provisions


def validate_corpus(provisions: list[ParsedProvision]) -> None:
    article_count = sum(1 for p in provisions if p.unit_type == "article")
    if article_count < 100:
        raise ValueError(
            f"Only {article_count} articles found; expected at least 100 "
            "(the AI Act has ~119) - refusing to load a suspiciously incomplete corpus"
        )

    id_counts = Counter(p.citation_id for p in provisions)
    duplicates = sorted(cid for cid, n in id_counts.items() if n > 1)
    if duplicates:
        raise ValueError(f"Duplicate citation_id(s) found: {duplicates}")

    citation_ids = set(id_counts)
    text_required = {"paragraph", "point", "annex_point"}

    for p in provisions:
        if p.unit_type in text_required and not p.text_content.strip():
            raise ValueError(
                f"Empty text_content for {p.citation_id!r} ({p.unit_type})"
            )
        if (
            p.parent_citation_id is not None
            and p.parent_citation_id not in citation_ids
        ):
            raise ValueError(
                f"{p.citation_id!r} has parent_citation_id={p.parent_citation_id!r}, "
                "which does not exist in this corpus"
            )


def load_corpus(
    session: Session, corpus_metadata: dict, provisions: list[ParsedProvision]
) -> int:
    existing_id = session.execute(
        select(CorpusVersion.id).where(
            CorpusVersion.content_hash == corpus_metadata["content_hash"]
        )
    ).scalar_one_or_none()
    if existing_id is not None:
        return existing_id

    try:
        corpus_version = CorpusVersion(
            celex=corpus_metadata["celex"],
            eli=None,
            title=corpus_metadata["title"],
            consolidated_date=corpus_metadata["consolidated_date"],
            valid_from=corpus_metadata["valid_from"],
            valid_to=None,
            source_url=corpus_metadata["source_url"],
            content_hash=corpus_metadata["content_hash"],
        )
        session.add(corpus_version)
        session.flush()  # assigns corpus_version.id without committing

        citation_to_row: dict[str, Provision] = {}
        for parsed in provisions:
            parent_row = (
                citation_to_row.get(parsed.parent_citation_id)
                if parsed.parent_citation_id is not None
                else None
            )
            row = Provision(
                corpus_version_id=corpus_version.id,
                citation_id=parsed.citation_id,
                eid=parsed.eid,
                parent_id=parent_row.id if parent_row is not None else None,
                unit_type=parsed.unit_type,
                number=parsed.number,
                heading=parsed.heading,
                text_content=parsed.text_content,
                amendment_marker=parsed.amendment_marker,
                ordinal=parsed.ordinal,
            )
            session.add(row)
            session.flush()  # assigns row.id so descendants can reference it
            citation_to_row[parsed.citation_id] = row

        session.commit()
        return corpus_version.id
    except Exception:
        session.rollback()
        raise
