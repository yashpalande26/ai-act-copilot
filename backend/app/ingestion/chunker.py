import hashlib
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Provision

LEAF_UNIT_TYPES = {"paragraph", "point", "annex_point"}
MAX_CHUNK_CHARS = 2000
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _render_segments(segments: list[str], *, is_annex: bool) -> str:
    parts: list[str] = []
    for seg in segments:
        if seg.startswith("art_"):
            parts.append(f"Article {seg[4:]}")
        elif seg.startswith("anx_"):
            parts.append(f"Annex {seg[4:]}")
        elif seg.startswith("par_"):
            parts.append(f"paragraph {seg[4:]}")
        elif seg.startswith("pt_"):
            value = seg[3:]
            parts.append(f"point {value}" if is_annex else f"point ({value})")
        elif seg.startswith("sub_"):
            value = seg[4:]
            if parts:
                parts[-1] = f"{parts[-1]}({value})"
            else:
                parts.append(f"({value})")
    return ", ".join(parts)


def citation_label(citation_id: str) -> str:
    """Full readable label, e.g. 'art_6.par_2.pt_a' -> 'Article 6, paragraph 2, point (a)',
    'anx_III.pt_5.sub_b' -> 'Annex III, point 5(b)'."""
    return _render_segments(
        citation_id.split("."), is_annex=citation_id.startswith("anx_")
    )


def _relative_label(citation_id: str, ancestor_citation_id: str) -> str:
    """Label for citation_id's segments after its ancestor's own segment,
    e.g. ('art_6.par_2.pt_a', 'art_6') -> 'paragraph 2, point (a)'."""
    remainder = citation_id[len(ancestor_citation_id) + 1 :]
    is_annex = citation_id.startswith("anx_")
    return _render_segments(remainder.split("."), is_annex=is_annex)


def build_contextual_prefix(
    ancestor_label: str, ancestor_heading: str | None, provision_label: str
) -> str:
    heading_part = f" ({ancestor_heading})" if ancestor_heading else ""
    # An empty provision label is the container itself (a single-paragraph
    # article chunked as its own leaf): no trailing ", ".
    label_part = f", {provision_label}" if provision_label else ""
    return f"EU AI Act — {ancestor_label}{heading_part}{label_part}:\n"


def split_long_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text into sentence-boundary chunks, each <= max_chars where
    possible. Returns [text] unchanged if it already fits."""
    if len(text) <= max_chars:
        return [text]

    sentences = _SENTENCE_SPLIT_RE.split(text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > max_chars and current:
            parts.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _find_container_ancestor(
    provision: Provision, by_id: dict[int, Provision]
) -> Provision:
    current = provision
    while current.unit_type not in ("article", "annex"):
        if current.parent_id is None:
            raise ValueError(
                f"{current.citation_id!r} has no parent and is not an article/annex root"
            )
        current = by_id[current.parent_id]
    return current


def is_leaf(provision: Provision, has_children: bool) -> bool:
    """What gets a chunk: paragraphs, points and annex points, and (since
    23 Sep 2026) a childless article whose text is a body rather than its
    heading, i.e. a single-paragraph article. Article and annex rows that
    merely hold their heading stay containers."""
    if provision.unit_type in LEAF_UNIT_TYPES:
        return True
    if provision.unit_type == "article" and not has_children:
        text = (provision.text_content or "").strip()
        return bool(text) and text != (provision.heading or "").strip()
    return False


def chunk_rows_for(
    provision: Provision, by_id: dict[int, Provision], corpus_version_id: int
) -> list[Chunk]:
    """The Chunk rows one leaf provision produces (unsaved)."""
    text = (provision.text_content or "").strip()
    if not text:
        return []
    ancestor = _find_container_ancestor(provision, by_id)
    ancestor_label = citation_label(ancestor.citation_id)
    provision_label = (
        ""
        if ancestor.id == provision.id
        else _relative_label(provision.citation_id, ancestor.citation_id)
    )
    parts = split_long_text(text)
    total = len(parts)
    rows: list[Chunk] = []
    for i, part_text in enumerate(parts, start=1):
        label = (
            provision_label if total == 1 else f"{provision_label} (part {i}/{total})"
        )
        prefix = build_contextual_prefix(ancestor_label, ancestor.heading, label)
        index_text = prefix + part_text
        rows.append(
            Chunk(
                corpus_version_id=corpus_version_id,
                provision_id=provision.id,
                parent_provision_id=ancestor.id,
                chunk_text=part_text,
                index_text=index_text,
                embedding=None,
                char_start=None,
                char_end=None,
                content_hash=hashlib.sha256(index_text.encode("utf-8")).hexdigest(),
                token_count=None,
            )
        )
    return rows


def _children_map(provisions: list[Provision]) -> set[int]:
    return {p.parent_id for p in provisions if p.parent_id is not None}


def build_missing_chunks(session: Session, corpus_version_id: int) -> int:
    """Add chunks only for leaves that have none. Never deletes, never
    touches an existing chunk or its embedding: the incremental path used to
    backfill provisions added after the first ingest (23 Sep 2026)."""
    provisions = (
        session.execute(
            select(Provision).where(Provision.corpus_version_id == corpus_version_id)
        )
        .scalars()
        .all()
    )
    by_id = {p.id: p for p in provisions}
    parents = _children_map(provisions)
    chunked = set(
        session.execute(
            select(Chunk.provision_id).where(
                Chunk.corpus_version_id == corpus_version_id
            )
        )
        .scalars()
        .all()
    )
    added = 0
    for provision in provisions:
        if provision.id in chunked or not is_leaf(provision, provision.id in parents):
            continue
        for row in chunk_rows_for(provision, by_id, corpus_version_id):
            session.add(row)
            added += 1
    session.flush()
    return added


def build_chunks(session: Session, corpus_version_id: int) -> int:
    session.execute(delete(Chunk).where(Chunk.corpus_version_id == corpus_version_id))

    provisions = (
        session.execute(
            select(Provision).where(Provision.corpus_version_id == corpus_version_id)
        )
        .scalars()
        .all()
    )
    by_id = {p.id: p for p in provisions}
    parents = _children_map(provisions)

    try:
        chunk_count = 0
        for provision in provisions:
            if not is_leaf(provision, provision.id in parents):
                continue
            for row in chunk_rows_for(provision, by_id, corpus_version_id):
                session.add(row)
                chunk_count += 1
        session.commit()
        return chunk_count
    except Exception:
        session.rollback()
        raise
