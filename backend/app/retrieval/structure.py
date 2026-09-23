"""The Act's container structure: chapters, their sections, the articles each
holds, and the annexes. Derived by scripts/build_structure.py from the cached
consolidated HTML (the corpus tables hold provisions only, with no chapter or
section rows) and committed as JSON next to this module. Read-only lookups.
"""

import json
from functools import lru_cache
from pathlib import Path

STRUCTURE_PATH = (
    Path(__file__).resolve().parent / "structure" / "02024R1689-20260727.json"
)


@lru_cache(maxsize=1)
def load_structure(path: Path = STRUCTURE_PATH) -> dict:
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def _index() -> dict:
    """Precomputed maps: article -> (chapter, section|None); chapter -> articles;
    (chapter, section) -> articles; chapter -> first article of each section."""
    data = load_structure()
    article_location: dict[str, tuple[str, str | None]] = {}
    chapter_articles: dict[str, list[str]] = {}
    section_articles: dict[tuple[str, str], list[str]] = {}
    section_heads: dict[str, list[str]] = {}
    for c in data["chapters"]:
        num = c["number"]
        chapter_articles[num] = list(c["articles"])
        for a in c["articles"]:
            article_location.setdefault(a, (num, None))
        heads = []
        for s in c["sections"]:
            section_articles[(num, s["number"])] = list(s["articles"])
            for a in s["articles"]:
                article_location[a] = (num, s["number"])
            if s["articles"]:
                heads.append(s["articles"][0])
        section_heads[num] = heads
    return {
        "article_location": article_location,
        "chapter_articles": chapter_articles,
        "section_articles": section_articles,
        "section_heads": section_heads,
        "annexes": set(data["annexes"]),
        "annex_sections": {
            k: [s["id"] for s in v] for k, v in data.get("annex_sections", {}).items()
        },
    }


def location_of(article_root: str) -> tuple[str, str | None] | None:
    """(chapter number, section number or None) for an article id like
    "art_16", or None when the article is not in the map."""
    return _index()["article_location"].get(article_root)


def section_articles(chapter: str, section: str) -> list[str]:
    return list(_index()["section_articles"].get((chapter, section), []))


def chapter_articles(chapter: str) -> list[str]:
    return list(_index()["chapter_articles"].get(chapter, []))


def chapter_section_heads(chapter: str) -> list[str]:
    """The first article of each section of a chapter; the chapter's own
    articles when it has no sections. What a bare chapter reference expands
    to: its shape, not its every article."""
    heads = _index()["section_heads"].get(chapter, [])
    return list(heads) if heads else chapter_articles(chapter)


def chapters_with_section(section: str) -> list[str]:
    """Chapters that have a section with this number."""
    return sorted(
        {c for (c, s) in _index()["section_articles"] if s == section},
        key=lambda r: list(_index()["chapter_articles"]).index(r),
    )


def is_annex(annex_root: str) -> bool:
    return annex_root in _index()["annexes"]


def annex_sections(annex_root: str) -> list[str]:
    """Section ids of a sectioned annex ("anx_I" -> ["anx_I.sec_A",
    "anx_I.sec_B"]); empty for an unsectioned annex."""
    return list(_index()["annex_sections"].get(annex_root, []))
