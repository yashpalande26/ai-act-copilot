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
    return f"EU AI Act — {ancestor_label}{heading_part}, {provision_label}:\n"


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

    try:
        chunk_count = 0
        for provision in provisions:
            if provision.unit_type not in LEAF_UNIT_TYPES:
                continue
            text = (provision.text_content or "").strip()
            if not text:
                continue

            ancestor = _find_container_ancestor(provision, by_id)
            ancestor_label = citation_label(ancestor.citation_id)
            provision_label = _relative_label(
                provision.citation_id, ancestor.citation_id
            )

            parts = split_long_text(text)
            total = len(parts)
            for i, part_text in enumerate(parts, start=1):
                label = (
                    provision_label
                    if total == 1
                    else f"{provision_label} (part {i}/{total})"
                )
                prefix = build_contextual_prefix(
                    ancestor_label, ancestor.heading, label
                )
                index_text = prefix + part_text
                session.add(
                    Chunk(
                        corpus_version_id=corpus_version_id,
                        provision_id=provision.id,
                        parent_provision_id=ancestor.id,
                        chunk_text=part_text,
                        index_text=index_text,
                        embedding=None,
                        char_start=None,
                        char_end=None,
                        content_hash=hashlib.sha256(
                            index_text.encode("utf-8")
                        ).hexdigest(),
                        token_count=None,
                    )
                )
                chunk_count += 1

        session.commit()
        return chunk_count
    except Exception:
        session.rollback()
        raise
