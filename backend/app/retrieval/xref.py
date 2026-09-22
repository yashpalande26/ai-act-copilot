"""Cross-reference retrieval expansion (22 Sep 2026). Deterministic, one hop,
capped, no model, no network.

The Act points at itself constantly: Article 16(a) says providers shall
"ensure that their high-risk AI systems are compliant with the requirements
set out in Section 2", and the requirements are Articles 8 to 15, which a
question about "the requirements set out in Section 2" never retrieves on its
own (measured live: refused). This module resolves such references to their
TARGET provisions and hands the retriever their chunks.

Sources, in priority order:
  1. the question itself: any "Section N [of Chapter X]", "Chapter X",
     "Annex X", "Article N", "Articles N to M", "Articles N and M";
  2. the top XREF_SOURCE_CHUNKS retrieved passages, but only references that
     sit behind a pointer phrase ("referred to in", "set out in", "laid down
     in", "in accordance with", "pursuant to", "listed in", "provided for
     in", "under"), never a passage's own article.
Resolution uses the structure map (app.retrieval.structure, derived from the
source document): a section expands to its articles; a bare "Section N"
takes the chapter the highest-ranked retrieved passage mentioning it names
(explicitly, or its own) and is dropped when no passage settles it; a chapter expands to the first article of each
of its sections (its shape, not its 44 articles); an annex to itself; an
article to itself. A range "Articles 9 to 15" expands numerically.

Selection: one chunk per target provision first (its opening passage), then
further passages of each target round-robin. Passages already in the
candidate pool are never added twice or moved. Two regimes, measured on
22 Sep 2026: a reference the QUESTION makes is a strong signal and gets up to
MAX_XREF_CHUNKS chunks at XREF_POSITION, after the fused top five and the
dense-anchor slot; a pointer found only inside a retrieved passage is
speculative (it fired on 22 of 39 eval turns and, at the same cap and
position, evicted the gold of two follow-ups; at two tail chunks it still
cost one follow-up two judge points), so it is used only when the question
names nothing itself, adds at most XREF_POINTER_CHUNKS (zero by default),
and enters at the tail of the context slice.
"""

import re
from dataclasses import dataclass

from app.retrieval import structure
from app.retrieval.search import FusedResult, SearchResult

MAX_XREF_CHUNKS = 10  # for references the QUESTION makes
XREF_POSITION = 6  # 0-indexed: after the top five and the anchor slot
# Pointers found only inside retrieved passages ("in accordance with Article
# 48" inside Article 16(h)). Measured 22 Sep 2026 at 2 chunks placed at the
# tail of the slice: no gold gained on any eval item, and the penalties
# follow-up's faithfulness fell from 5,5,5 to 3,3,5 on repeats because the
# Article 48 passage pulled the answer towards the CE marking rules. Off (0)
# until a case shows value; the mechanism is kept and tested.
XREF_POINTER_CHUNKS = 0
XREF_SOURCE_CHUNKS = 3  # passages read for pointers

_SECTION = re.compile(
    r"\bSection\s+(\d+)(?:\s+of\s+(?:this\s+)?Chapter\s+([IVXLC]+))?", re.IGNORECASE
)
_CHAPTER = re.compile(r"\bChapter\s+([IVXLC]+)\b")
_ANNEX = re.compile(r"\bAnnex(?:es)?\s+([IVXLC]+)\b")
_ARTICLE_RANGE = re.compile(r"\bArticles\s+(\d+)\s+to\s+(\d+)\b", re.IGNORECASE)
_ARTICLE = re.compile(
    r"\bArticles?\s+(\d+[a-z]?)((?:\s*(?:,|and|or)\s*\d+[a-z]?)*)", re.IGNORECASE
)
_POINTER = re.compile(
    r"\b(?:referred to in|set out in|laid down in|in accordance with|pursuant to|"
    r"listed in|provided for in|under|of)\s+(?:this\s+)?"
    r"((?:Section|Chapter|Annex|Articles?)\s+[^.;:]{0,60})",
    re.IGNORECASE,
)
_MAX_RANGE = 20


@dataclass(frozen=True)
class Reference:
    kind: str  # section | chapter | annex | article
    number: str
    chapter: str | None = None  # for a section


def references_in(text: str) -> list[Reference]:
    """Every reference in a text, in order of appearance, deduplicated."""
    out: list[Reference] = []
    seen: set = set()

    def add(ref: Reference):
        if ref not in seen:
            seen.add(ref)
            out.append(ref)

    for m in _SECTION.finditer(text):
        add(
            Reference("section", m.group(1), m.group(2).upper() if m.group(2) else None)
        )
    for m in _CHAPTER.finditer(text):
        add(Reference("chapter", m.group(1)))
    for m in _ANNEX.finditer(text):
        add(Reference("annex", m.group(1)))
    for m in _ARTICLE_RANGE.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if 0 < b - a <= _MAX_RANGE:
            for n in range(a, b + 1):
                add(Reference("article", str(n)))
    for m in _ARTICLE.finditer(text):
        if _ARTICLE_RANGE.match(text, m.start()):
            continue
        add(Reference("article", m.group(1).lower()))
        for n in re.findall(r"\d+[a-z]?", m.group(2) or ""):
            add(Reference("article", n.lower()))
    return out


def pointed_references_in(text: str) -> list[Reference]:
    """References that follow a pointer phrase: what a passage sends the
    reader to, not what it merely mentions."""
    out: list[Reference] = []
    for m in _POINTER.finditer(text):
        for ref in references_in(m.group(1)):
            if ref not in out:
                out.append(ref)
    return out


def _article_root(citation_id: str) -> str:
    return citation_id.split(".")[0]


@dataclass(frozen=True)
class Resolution:
    from_query: tuple[str, ...]  # provision roots the question itself names
    from_pointers: tuple[
        str, ...
    ]  # roots the top passages point at (used only when from_query is empty)


def resolve_references(query: str, top_chunks: list[SearchResult]) -> Resolution:
    """Target provision roots ("art_9", "anx_III"), in priority order."""
    chunk_chapters: dict[str, str] = {}
    for c in top_chunks:
        loc = structure.location_of(_article_root(c.citation_id))
        if loc:
            chunk_chapters[c.citation_id] = loc[0]

    def chapter_for_bare_section(number: str) -> str | None:
        """The chapter a bare "Section N" means. The Act writes "Section 2"
        inside Chapter III for Chapter III's Section 2, and "Section 2 of
        Chapter III" from elsewhere. So: the highest-ranked retrieved passage
        that mentions this section decides, by the chapter it names
        explicitly if it does, else by its own chapter. Nothing mentioning it
        and no unique chapter: dropped rather than guessed."""
        for c in top_chunks:
            for r in references_in(c.chunk_text):
                if r.kind == "section" and r.number == number:
                    if r.chapter:
                        return r.chapter
                    if c.citation_id in chunk_chapters:
                        return chunk_chapters[c.citation_id]
        candidates = structure.chapters_with_section(number)
        return candidates[0] if len(candidates) == 1 else None

    def expand(ref: Reference, own_chapter: str | None) -> list[str]:
        if ref.kind == "section":
            chapter = ref.chapter or own_chapter or chapter_for_bare_section(ref.number)
            return structure.section_articles(chapter, ref.number) if chapter else []
        if ref.kind == "chapter":
            return structure.chapter_section_heads(ref.number)
        if ref.kind == "annex":
            root = f"anx_{ref.number}"
            return [root] if structure.is_annex(root) else []
        root = f"art_{ref.number}"
        return [root] if structure.location_of(root) else []

    def dedupe(seq: list[str]) -> tuple[str, ...]:
        out: list[str] = []
        for r in seq:
            if r not in out:
                out.append(r)
        return tuple(out)

    from_query = dedupe([r for ref in references_in(query) for r in expand(ref, None)])
    pointers: list[str] = []
    for c in top_chunks[:XREF_SOURCE_CHUNKS]:
        own = _article_root(c.citation_id)
        for ref in pointed_references_in(c.chunk_text):
            pointers += [
                r for r in expand(ref, chunk_chapters.get(c.citation_id)) if r != own
            ]
    return Resolution(from_query=from_query, from_pointers=dedupe(pointers))


def select_chunks(
    by_root: dict[str, list[SearchResult]],
    present: set[int],
    cap: int = MAX_XREF_CHUNKS,
) -> list[SearchResult]:
    """One opening chunk per target first, then further chunks round-robin,
    skipping chunks already in the pool, up to `cap`."""
    chosen: list[SearchResult] = []
    depth = 0
    while len(chosen) < cap:
        added = False
        for candidates in by_root.values():
            rows = [r for r in candidates if r.chunk_id not in present]
            if depth < len(rows) and len(chosen) < cap:
                chosen.append(rows[depth])
                added = True
        if not added:
            break
        depth += 1
    return chosen


def apply_xref_expansion(
    all_fused: list[FusedResult],
    extra: list[SearchResult],
    *,
    position: int = XREF_POSITION,
) -> tuple[list[FusedResult], int]:
    """Insert resolved chunks at `position`, never duplicating or moving a
    chunk already in the pool. Pure. Returns (fused, number added)."""
    present = {f.result.chunk_id for f in all_fused}
    new = [
        FusedResult(result=r, rrf_score=0.0, vector_rank=None, lexical_rank=None)
        for r in extra
        if r.chunk_id not in present
    ]
    if not new:
        return all_fused, 0
    at = min(position, len(all_fused))
    return [*all_fused[:at], *new, *all_fused[at:]], len(new)
