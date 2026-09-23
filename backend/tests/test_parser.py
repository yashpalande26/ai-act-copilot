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


def test_single_paragraph_article_body_is_kept_on_the_article_row():
    # Article 32 has one bare <p class="norm"> and no numbered paragraph;
    # before 23 Sep 2026 only the heading survived (corpus audit).
    provisions = parse_article(_load_fixture("article_32.html"))
    assert [p.unit_type for p in provisions] == ["article"]
    art = provisions[0]
    assert (
        art.heading
        == "Presumption of conformity with requirements relating to notified bodies"
    )
    assert art.text_content.startswith(
        "Where a conformity assessment body demonstrates"
    )
    assert "Official Journal of the European Union" in art.text_content
    assert art.text_content != art.heading


def test_two_bare_paragraphs_are_joined_into_one_body():
    provisions = parse_article(_load_fixture("article_85.html"))
    assert len(provisions) == 1
    body = provisions[0].text_content
    assert body.startswith(
        "Without prejudice to other administrative or judicial remedies"
    )
    assert "In accordance with Regulation (EU) 2019/1020" in body


def test_numbered_article_row_still_holds_only_its_heading():
    provisions = parse_article(_load_fixture("article_06.html"))
    art = provisions[0]
    assert art.text_content == art.heading and len(provisions) > 1
