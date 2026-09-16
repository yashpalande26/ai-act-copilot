from datetime import date
from pathlib import Path

import pytest

from app.ingestion.loader import build_corpus, validate_corpus
from app.ingestion.models import ParsedProvision

CORPUS_HTML_PATH = (
    Path(__file__).parent.parent / "data" / "aiact_02024R1689-20260727.html"
)
SOURCE_URL = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02024R1689-20260727"
)


def _load_full_corpus_html() -> str:
    if not CORPUS_HTML_PATH.exists():
        pytest.skip(f"{CORPUS_HTML_PATH} not present; run fetch_corpus.py first")
    return CORPUS_HTML_PATH.read_text(encoding="utf-8")


def _build(html: str):
    return build_corpus(
        html,
        celex="02024R1689-20260727",
        consolidated_date=date(2026, 7, 27),
        valid_from=date(2026, 7, 27),
        source_url=SOURCE_URL,
    )


def test_build_corpus_full_document_article_count_and_stable_hash():
    html = _load_full_corpus_html()
    metadata1, provisions1 = _build(html)
    article_count = sum(1 for p in provisions1 if p.unit_type == "article")
    assert article_count >= 100

    metadata2, _ = _build(html)
    assert metadata1["content_hash"] == metadata2["content_hash"]


def test_validate_corpus_passes_on_real_parsed_corpus():
    html = _load_full_corpus_html()
    _, provisions = _build(html)
    validate_corpus(provisions)  # should not raise


def _fake_articles(n: int) -> list[ParsedProvision]:
    return [
        ParsedProvision(
            citation_id=f"art_{i}",
            eid=f"art_{i}",
            unit_type="article",
            number=str(i),
            heading=f"Article {i}",
            text_content=f"Article {i}",
            parent_citation_id=None,
            amendment_marker=None,
            ordinal=0,
        )
        for i in range(1, n + 1)
    ]


def test_validate_corpus_raises_on_empty_text():
    provisions = _fake_articles(100) + [
        ParsedProvision(
            citation_id="art_1.par_1",
            eid=None,
            unit_type="paragraph",
            number="1",
            heading=None,
            text_content="",
            parent_citation_id="art_1",
            amendment_marker=None,
            ordinal=1,
        )
    ]
    with pytest.raises(ValueError):
        validate_corpus(provisions)


def test_validate_corpus_raises_on_unresolved_parent():
    provisions = _fake_articles(100) + [
        ParsedProvision(
            citation_id="art_1.par_1",
            eid=None,
            unit_type="paragraph",
            number="1",
            heading=None,
            text_content="Some real text",
            parent_citation_id="art_999",
            amendment_marker=None,
            ordinal=1,
        )
    ]
    with pytest.raises(ValueError):
        validate_corpus(provisions)
