import copy
import re

from bs4 import BeautifulSoup, Tag

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
    ordinal = 1

    for tag in root.find_all(True):
        classes = tag.get("class") or []

        if tag.name == "p" and "modref" in classes:
            code = _marker_code(tag)
            current_marker = None if code == "B" else code
            continue

        if tag.name == "div" and classes == ["norm"]:
            marker_span = tag.find("span", class_="no-parag", recursive=False)
            if marker_span is None:
                continue
            par_number = _clean_text(marker_span.get_text()).rstrip(".").strip()
            citation_id = f"art_{number}.par_{par_number}"
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
            if current_paragraph_citation is None:
                raise ValueError("Point found before any paragraph in article")
            letter = _strip_marker_punctuation(marker_tag.get_text())
            citation_id = f"{current_paragraph_citation}.pt_{letter}"
            text_content = _own_text(content_tag, exclude_classes=("modref",))
            provisions.append(
                ParsedProvision(
                    citation_id=citation_id,
                    eid=None,
                    unit_type="point",
                    number=f"({letter})",
                    heading=None,
                    text_content=text_content,
                    parent_citation_id=current_paragraph_citation,
                    amendment_marker=current_marker,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
            continue

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
            citation_id = f"anx_{roman}.pt_{number}"
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
            citation_id = f"{current_point_citation}.sub_{letter}"
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


def _validate(
    provisions: list[ParsedProvision], expected_types: tuple[str, ...]
) -> None:
    for provision in provisions:
        if provision.unit_type in expected_types and not provision.text_content:
            raise ValueError(
                f"Empty text_content for {provision.citation_id!r} ({provision.unit_type})"
            )
