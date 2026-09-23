from pathlib import Path

import pytest

from app.ingestion.parser import (
    is_sectioned_annex,
    parse_annex,
    parse_article,
    parse_recitals,
    parse_sectioned_annex,
)

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


# --- sectioned annexes (Annex I, 23 Sep 2026) ---------------------------------


def test_annex_i_is_sectioned_and_annex_iii_is_not():
    assert is_sectioned_annex(_load_fixture("annex_I.html")) is True
    assert is_sectioned_annex(_load_fixture("annex_III.html")) is False


def test_annex_i_sections_numbering_and_markers():
    provisions = parse_sectioned_annex(_load_fixture("annex_I.html"))
    by = {p.citation_id: p for p in provisions}
    assert by["anx_I"].unit_type == "annex"
    assert by["anx_I"].heading == "List of Union harmonisation legislation"
    assert by["anx_I.sec_A"].unit_type == "annex_section"
    assert by["anx_I.sec_A"].heading.startswith(
        "List of Union harmonisation legislation based on the New Legislative Framework"
    )
    assert by["anx_I.sec_B"].heading == "List of other Union harmonisation legislation"
    # numbering runs through the annex: 1 to 12 in A, 13 to 21 in B
    points = [p for p in provisions if p.unit_type == "annex_point"]
    assert [p.number for p in points] == [str(i) for i in range(1, 22)]
    assert all(p.parent_citation_id == "anx_I.sec_A" for p in points[:12])
    assert all(p.parent_citation_id == "anx_I.sec_B" for p in points[12:])
    # item 1 deleted by M1: a row with the marker and no text, never chunked
    deleted = by["anx_I.sec_A.pt_1"]
    assert deleted.deleted is True
    assert deleted.amendment_marker == "M1" and deleted.text_content == ""
    # item 21 inserted by M1; its neighbours carry no marker
    assert by["anx_I.sec_B.pt_21"].amendment_marker == "M1"
    assert by["anx_I.sec_B.pt_21"].text_content.startswith("Regulation (EU) 2023/1230")
    assert by["anx_I.sec_B.pt_20"].amendment_marker is None
    assert by["anx_I.sec_A.pt_2"].amendment_marker is None
    # the number is stripped from the text; the text is the item
    assert by["anx_I.sec_A.pt_2"].text_content.startswith("Directive 2009/48/EC")
    assert by["anx_I.sec_A.pt_4"].text_content.endswith(
        "lifts (OJ L 96, 29.3.2014, p. 251);"
    )
    assert sum(1 for p in points if p.text_content) == 20


# --- recitals (ADR-32) --------------------------------------------------------------


def test_recital_row_from_the_oj_act_markup():
    html = _load_fixture("recital_58.html")
    (rec,) = parse_recitals(html)
    assert rec.citation_id == "rec_58" and rec.unit_type == "recital"
    assert rec.eid == "32024R1689:rct_58" and rec.number == "58" and rec.ordinal == 58
    assert rec.heading == "explanatory, non-binding"
    assert rec.text_content.startswith(
        "Another area in which the use of AI systems deserves"
    )
    assert not rec.text_content.startswith("(58)")
    assert "creditworthiness" in rec.text_content


def test_recital_numbering_must_be_contiguous_from_one():
    import pytest

    html = _load_fixture("recital_58.html")
    # a lone recital 58 in a full parse is a numbering gap: the real parse of the
    # whole preamble starts at 1, so the fixture is checked through the row API
    # above; the contiguity guard is exercised here by feeding two copies.
    with pytest.raises(ValueError):
        parse_recitals(html.replace('id="rct_58"', 'id="rct_2"') + html)
