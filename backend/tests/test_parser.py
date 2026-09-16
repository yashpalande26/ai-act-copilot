from pathlib import Path

import pytest

from app.ingestion.parser import parse_annex, parse_article

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_article_5_parses_without_error():
    provisions = parse_article(_load_fixture("article_05.html"))
    by_id = {p.citation_id: p for p in provisions}
    assert "art_5" in by_id
    assert by_id["art_5"].unit_type == "article"


def test_article_6_paragraph_2_exists():
    provisions = parse_article(_load_fixture("article_06.html"))
    citation_ids = {p.citation_id for p in provisions}
    assert "art_6.par_2" in citation_ids


def test_article_6_amendment_marker_present():
    provisions = parse_article(_load_fixture("article_06.html"))
    markers = {p.amendment_marker for p in provisions}
    assert "M1" in markers


def test_article_6_modref_text_not_leaked_into_content():
    provisions = parse_article(_load_fixture("article_06.html"))
    for provision in provisions:
        assert "M1" not in provision.text_content
        assert "▼" not in provision.text_content


def test_annex_iii_parses_and_has_root_provision():
    provisions = parse_annex(_load_fixture("annex_III.html"))
    citation_ids = {p.citation_id for p in provisions}
    assert "anx_III" in citation_ids


def test_annex_iii_point_5_sub_points():
    provisions = parse_annex(_load_fixture("annex_III.html"))
    by_id = {p.citation_id: p for p in provisions}
    assert "anx_III.pt_5.sub_b" in by_id
    assert "creditworthiness" in by_id["anx_III.pt_5.sub_b"].text_content
    assert "anx_III.pt_5.sub_c" in by_id
    assert "insurance" in by_id["anx_III.pt_5.sub_c"].text_content


def test_malformed_article_input_raises_value_error():
    with pytest.raises(ValueError):
        parse_article("<div>nonsense</div>")


def test_malformed_annex_input_raises_value_error():
    with pytest.raises(ValueError):
        parse_annex("<div>nonsense</div>")
