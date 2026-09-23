import copy
import re
import warnings

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

from app.ingestion.models import ParsedProvision


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _own_text(tag: Tag, exclude_classes: tuple[str, ...]) -> str:
    """This tag's own text, excluding descendants matching exclude_classes.

    Operates on a detached copy of the tag, so the tree being walked by the
    caller is never mutated.
    """
    clone = copy.copy(tag)
    for cls in exclude_classes:
        for nested in clone.find_all(class_=cls):
            nested.decompose()
    return _clean_text(clone.get_text())


def _is_nested_point(tag: Tag) -> bool:
    """True if this grid-container point sits inside another grid-container
    point (i.e. it's a sub-point of some enclosing point, not top-level).
    """
    for ancestor in tag.parents:
        classes = ancestor.get("class") if hasattr(ancestor, "get") else None
        if classes and "grid-container" in classes:
            return True
    return False


def _marker_code(modref_tag: Tag) -> str:
    return _clean_text(modref_tag.get_text()).lstrip("▼").strip()


def _strip_marker_punctuation(text: str) -> str:
    return text.strip().strip("().").strip()


def _dedupe_citation_id(base_id: str, used_ids: set[str]) -> str:
    """Return base_id, or base_id with a numeric suffix if it's already been
    used. Real cases this handles: a single numbered paragraph containing
    two separate lettered lists (letters legitimately restart at "(a)"), and
    bullet lists whose marker (e.g. "-") carries no distinguishing text at
    all. The first occurrence of any id is always left unmodified.
    """
    if base_id not in used_ids:
        used_ids.add(base_id)
        return base_id
    n = 2
    while f"{base_id}_{n}" in used_ids:
        n += 1
    deduped = f"{base_id}_{n}"
    used_ids.add(deduped)
    return deduped


def split_document(html: str) -> tuple[list[str], list[str]]:
    """Split the full AI Act HTML into per-article and per-annex blocks.

    Reuses the same structural selectors parse_article/parse_annex expect.
    The "." not in tag["id"] filter excludes compound sub-ids (e.g. the
    article title anchor art_6.tit_1) that a loose "^art_"/"^anx_" search
    would otherwise also match, since BeautifulSoup's id=regex does a
    search, not a full match.
    """
    soup = BeautifulSoup(html, "lxml")

    article_roots = [
        tag
        for tag in soup.find_all(
            "div", class_="eli-subdivision", id=re.compile(r"^art_")
        )
        if "." not in tag["id"]
    ]
    annex_roots = [
        tag
        for tag in soup.find_all("div", id=re.compile(r"^anx_"))
        if "." not in tag["id"]
    ]

    return [str(tag) for tag in article_roots], [str(tag) for tag in annex_roots]


def parse_article(html: str) -> list[ParsedProvision]:
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("div", id=re.compile(r"^art_"))
    if root is None:
        raise ValueError("No article id (art_*) found in input HTML")

    match = re.match(r"^art_(.+)$", root["id"])
    number = match.group(1) if match else ""
    if not number:
        raise ValueError("Article number could not be extracted")

    heading_tag = root.find("p", class_="stitle-article-norm")
    heading = _clean_text(heading_tag.get_text()) if heading_tag else None

    provisions: list[ParsedProvision] = [
        ParsedProvision(
            citation_id=f"art_{number}",
            eid=f"art_{number}",
            unit_type="article",
            number=number,
            heading=heading,
            text_content=heading or "",
            parent_citation_id=None,
            amendment_marker=None,
            ordinal=0,
        )
    ]

    current_marker: str | None = None
    current_paragraph_citation: str | None = None
    used_citation_ids: set[str] = {f"art_{number}"}
    ordinal = 1

    for tag in root.find_all(True):
        classes = tag.get("class") or []

        if tag.name == "p" and "modref" in classes:
            code = _marker_code(tag)
            current_marker = None if code == "B" else code
            continue

        # A div.norm nested inside a point's own content is quoted text
        # (e.g. Article 108-style "Amendments to Regulation X" articles
        # quote new paragraph text being inserted into ANOTHER regulation,
        # reusing this same norm/no-parag markup) - not a real paragraph of
        # *this* article. Its text still ends up in the enclosing point's
        # own text_content; it just isn't independently emitted here.
        if tag.name == "div" and classes == ["norm"] and not _is_nested_point(tag):
            marker_span = tag.find("span", class_="no-parag", recursive=False)
            if marker_span is None:
                continue
            par_number = _clean_text(marker_span.get_text()).rstrip(".").strip()
            citation_id = _dedupe_citation_id(
                f"art_{number}.par_{par_number}", used_citation_ids
            )
            content_div = tag.find("div", recursive=False)
            text_content = (
                _own_text(content_div, exclude_classes=("grid-container", "modref"))
                if content_div is not None
                else ""
            )
            provisions.append(
                ParsedProvision(
                    citation_id=citation_id,
                    eid=None,
                    unit_type="paragraph",
                    number=par_number,
                    heading=None,
                    text_content=text_content,
                    parent_citation_id=f"art_{number}",
                    amendment_marker=current_marker,
                    ordinal=ordinal,
                )
            )
            current_paragraph_citation = citation_id
            ordinal += 1
            continue

        if (
            tag.name == "div"
            and "grid-container" in classes
            and "grid-list" in classes
            and not _is_nested_point(tag)
        ):
            marker_tag = tag.find("div", class_="grid-list-column-1")
            content_tag = tag.find("div", class_="grid-list-column-2")
            if marker_tag is None or content_tag is None:
                continue
            # Some articles (e.g. Article 3 "Definitions") have no numbered
            # paragraphs at all - just an intro sentence followed directly
            # by a point list under the article itself. When no paragraph
            # is currently open, the point's parent is the article.
            parent_citation = current_paragraph_citation or f"art_{number}"
            letter = _strip_marker_punctuation(marker_tag.get_text())
            citation_id = _dedupe_citation_id(
                f"{parent_citation}.pt_{letter}", used_citation_ids
            )
            text_content = _own_text(content_tag, exclude_classes=("modref",))
            provisions.append(
                ParsedProvision(
                    citation_id=citation_id,
                    eid=None,
                    unit_type="point",
                    number=f"({letter})",
                    heading=None,
                    text_content=text_content,
                    parent_citation_id=parent_citation,
                    amendment_marker=current_marker,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
            continue

    if len(provisions) == 1:
        # A single-paragraph article (Articles 32, 39, 85, 87, 94, 102 to 104
        # in the 27 Jul 2026 text): no numbered paragraph, no point list, the
        # body is one or more bare <p class="norm"> directly under the
        # article. Until 23 Sep 2026 only the heading was stored and the body
        # was in no provision row, so it was un-retrievable and un-citable
        # (found by the corpus audit). The body becomes the article's own
        # text_content; the chunker treats a childless article as a leaf and
        # its citation label stays "Article N", which is the legally correct
        # label for an unnumbered body.
        body = " ".join(
            t
            for t in (
                _own_text(para, exclude_classes=("modref",))
                for para in root.find_all("p", class_="norm", recursive=False)
            )
            if t
        )
        if body:
            provisions[0] = provisions[0].model_copy(update={"text_content": body})

    _validate(provisions, expected_types=("paragraph", "point"))
    return provisions


def parse_annex(html: str) -> list[ParsedProvision]:
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("div", id=re.compile(r"^anx_"))
    if root is None:
        raise ValueError("No annex id (anx_*) found in input HTML")

    match = re.match(r"^anx_(.+)$", root["id"])
    roman = match.group(1) if match else ""
    if not roman:
        raise ValueError("Annex number could not be extracted")

    heading_tag = root.find("p", class_="title-annex-2")
    heading = _clean_text(heading_tag.get_text()) if heading_tag else None

    provisions: list[ParsedProvision] = [
        ParsedProvision(
            citation_id=f"anx_{roman}",
            eid=f"anx_{roman}",
            unit_type="annex",
            number=roman,
            heading=heading,
            text_content=heading or "",
            parent_citation_id=None,
            amendment_marker=None,
            ordinal=0,
        )
    ]

    current_point_citation: str | None = None
    used_citation_ids: set[str] = {f"anx_{roman}"}
    ordinal = 1

    for tag in root.find_all(True):
        classes = tag.get("class") or []
        if not (
            tag.name == "div" and "grid-container" in classes and "grid-list" in classes
        ):
            continue

        marker_tag = tag.find("div", class_="grid-list-column-1")
        content_tag = tag.find("div", class_="grid-list-column-2")
        if marker_tag is None or content_tag is None:
            continue

        if not _is_nested_point(tag):
            number = _clean_text(marker_tag.get_text()).rstrip(".").strip()
            citation_id = _dedupe_citation_id(
                f"anx_{roman}.pt_{number}", used_citation_ids
            )
            text_content = _own_text(
                content_tag, exclude_classes=("grid-container", "modref")
            )
            provisions.append(
                ParsedProvision(
                    citation_id=citation_id,
                    eid=None,
                    unit_type="annex_point",
                    number=number,
                    heading=None,
                    text_content=text_content,
                    parent_citation_id=f"anx_{roman}",
                    amendment_marker=None,
                    ordinal=ordinal,
                )
            )
            current_point_citation = citation_id
            ordinal += 1
        else:
            if current_point_citation is None:
                raise ValueError("Sub-point found before any top-level point in annex")
            letter = _strip_marker_punctuation(marker_tag.get_text())
            citation_id = _dedupe_citation_id(
                f"{current_point_citation}.sub_{letter}", used_citation_ids
            )
            text_content = _own_text(content_tag, exclude_classes=("modref",))
            provisions.append(
                ParsedProvision(
                    citation_id=citation_id,
                    eid=None,
                    unit_type="annex_point",
                    number=f"({letter})",
                    heading=None,
                    text_content=text_content,
                    parent_citation_id=current_point_citation,
                    amendment_marker=None,
                    ordinal=ordinal,
                )
            )
            ordinal += 1

    _validate(provisions, expected_types=("annex_point",))
    return provisions


_SECTION_TITLE = re.compile(r"^Section\s+([A-Z0-9]+)\.?\s*(.*)$")
_NUMBERED_ITEM = re.compile(r"^(\d+)\.\s*(.*)$", re.DOTALL)
_DELETION = re.compile(r"^[\u2014\u2013\-]{3,}$")


def is_sectioned_annex(html: str) -> bool:
    """An annex laid out as titled sections (<p class="title-gr-seq-level-1">)
    rather than a grid list: Annexes I, VII, VIII, X, XI, XIV in the 27 Jul
    2026 text. Only the numbered-bare-paragraph shape (Annex I) is parsed so
    far; see parse_sectioned_annex."""
    return 'class="title-gr-seq-level-1"' in html


def parse_sectioned_annex(html: str) -> list[ParsedProvision]:
    """Annex with lettered or numbered sections whose items are numbered bare
    paragraphs ("2. Directive 2009/48/EC ..."). Citation scheme (23 Sep 2026):
    anx_<annex>.sec_<section>.pt_<n>; the section is a row of unit_type
    annex_section carrying the section heading. Numbering runs through the
    whole annex (Annex I: 1 to 12 in Section A, 13 to 21 in Section B). An
    amendment marker (M1 ...) applies to the items that follow it until the
    base-text marker (B). A marker followed by a dash run and no item is a
    deletion: the missing number is recorded as a deleted row with empty text
    and the marker, so the gap is explained and never chunked."""
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("div", id=re.compile(r"^anx_"))
    if root is None:
        raise ValueError("No annex id (anx_*) found in input HTML")
    match = re.match(r"^anx_(.+)$", root["id"])
    roman = match.group(1) if match else ""
    if not roman:
        raise ValueError("Annex number could not be extracted")
    annex_id = f"anx_{roman}"
    heading_tag = root.find("p", class_="title-annex-2")
    heading = _clean_text(heading_tag.get_text()) if heading_tag else None

    provisions: list[ParsedProvision] = [
        ParsedProvision(
            citation_id=annex_id,
            eid=annex_id,
            unit_type="annex",
            number=roman,
            heading=heading,
            text_content=heading or "",
            parent_citation_id=None,
            amendment_marker=None,
            ordinal=0,
        )
    ]
    used: set[str] = {annex_id}
    section_id: str | None = None
    current_marker: str | None = None
    last_number = 0
    ordinal = 1

    for tag in root.find_all("p"):
        classes = tag.get("class") or []
        if "title-gr-seq-level-1" in classes:
            title = _clean_text(tag.get_text())
            m = _SECTION_TITLE.match(title)
            if m is None:
                raise ValueError(f"Unrecognised section title in {annex_id}: {title!r}")
            letter, section_heading = m.group(1), _clean_text(m.group(2))
            section_id = _dedupe_citation_id(f"{annex_id}.sec_{letter}", used)
            provisions.append(
                ParsedProvision(
                    citation_id=section_id,
                    eid=None,
                    unit_type="annex_section",
                    number=letter,
                    heading=section_heading or None,
                    text_content=section_heading or title,
                    parent_citation_id=annex_id,
                    amendment_marker=None,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
            continue
        if "modref" in classes:
            # "M1", "B", or "M1 \u2014\u2014\u2014\u2014\u2014" when the amending act deleted an item
            raw = _marker_code(tag)
            code, _, trailing = raw.partition(" ")
            if _DELETION.match(trailing.strip()):
                # a deleted item: the number after the last one seen
                last_number += 1
                parent = section_id or annex_id
                provisions.append(
                    ParsedProvision(
                        citation_id=_dedupe_citation_id(
                            f"{parent}.pt_{last_number}", used
                        ),
                        eid=None,
                        unit_type="annex_point",
                        number=str(last_number),
                        heading=None,
                        text_content="",
                        parent_citation_id=parent,
                        amendment_marker=code,
                        ordinal=ordinal,
                        deleted=True,
                    )
                )
                ordinal += 1
                continue
            current_marker = None if code == "B" else code
            continue
        if "norm" in classes:
            text = _own_text(tag, exclude_classes=("modref",))
            m = _NUMBERED_ITEM.match(text)
            if m is None:
                continue  # an unnumbered paragraph in a sectioned annex: not this shape
            number, body = m.group(1), _clean_text(m.group(2))
            parent = section_id or annex_id
            provisions.append(
                ParsedProvision(
                    citation_id=_dedupe_citation_id(f"{parent}.pt_{number}", used),
                    eid=None,
                    unit_type="annex_point",
                    number=number,
                    heading=None,
                    text_content=body,
                    parent_citation_id=parent,
                    amendment_marker=current_marker,
                    ordinal=ordinal,
                )
            )
            last_number = int(number)
            ordinal += 1

    _validate(provisions, expected_types=("annex_point",))
    return provisions


def _validate(
    provisions: list[ParsedProvision], expected_types: tuple[str, ...]
) -> None:
    for provision in provisions:
        if provision.deleted:
            continue
        if provision.unit_type in expected_types and not provision.text_content:
            raise ValueError(
                f"Empty text_content for {provision.citation_id!r} ({provision.unit_type})"
            )


_RECITAL_MARK = re.compile(r"^\((\d+)\)\s*")
RECITAL_HEADING = "explanatory, non-binding"


def parse_recitals(
    html: str, source_celex: str = "32024R1689"
) -> list[ParsedProvision]:
    """The preamble of the ORIGINAL Official Journal act (CELEX 32024R1689),
    which the consolidated text drops. Each <div class="eli-subdivision"
    id="rct_N"> is one recital: a two-column table whose first cell holds the
    "(N)" marker and whose second holds the text. One row per recital,
    unit_type recital, citation id rec_N, eid <source_celex>:rct_N so the row
    itself says which document it came from, heading the fixed phrase that
    labels every recital chunk as explanatory and non-binding (ADR-32).
    Recitals are never amended by a consolidation, so the 2024 preamble is the
    current preamble."""
    with warnings.catch_warnings():
        # The OJ file is XHTML served as .xml; the HTML parser reads it fine.
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")
    provisions: list[ParsedProvision] = []
    for div in soup.find_all("div", id=re.compile(r"^rct_\d+$")):
        number = int(div["id"].split("_")[1])
        cells = div.find_all("td")
        text = (
            _clean_text(cells[-1].get_text(" "))
            if cells
            else _clean_text(div.get_text(" "))
        )
        text = _RECITAL_MARK.sub("", text, count=1)
        if not text:
            raise ValueError(f"Recital {number} has no text")
        provisions.append(
            ParsedProvision(
                citation_id=f"rec_{number}",
                eid=f"{source_celex}:rct_{number}",
                unit_type="recital",
                number=str(number),
                heading=RECITAL_HEADING,
                text_content=text,
                parent_citation_id=None,
                amendment_marker=None,
                ordinal=number,
            )
        )
    numbers = [int(p.number) for p in provisions]
    if numbers and numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        raise ValueError(
            f"Recital numbering is not contiguous: {numbers[:5]} ... {numbers[-3:]}"
        )
    return provisions
