from app.ingestion.chunker import (
    build_contextual_prefix,
    citation_label,
    split_long_text,
)


def test_citation_label_article_paragraph_point():
    assert citation_label("art_6.par_2.pt_a") == "Article 6, paragraph 2, point (a)"


def test_citation_label_annex_point_subpoint():
    assert citation_label("anx_III.pt_5.sub_b") == "Annex III, point 5(b)"


def test_build_contextual_prefix_with_heading():
    prefix = build_contextual_prefix(
        "Article 6",
        "Classification rules for high-risk AI systems",
        "paragraph 2, point (a)",
    )
    assert prefix == (
        "EU AI Act — Article 6 (Classification rules for high-risk AI systems), "
        "paragraph 2, point (a):\n"
    )


def test_build_contextual_prefix_without_heading():
    prefix = build_contextual_prefix("Annex III", None, "point 5(b)")
    assert prefix == "EU AI Act — Annex III, point 5(b):\n"


def test_split_long_text_short_text_is_one_chunk():
    text = "Short text that does not need splitting."
    assert split_long_text(text) == [text]


def test_split_long_text_splits_at_sentence_boundaries():
    sentence = "This is a test sentence used to build a long provision. "
    long_text = sentence * 60  # well over 2000 chars
    parts = split_long_text(long_text)
    assert len(parts) > 1
    assert all(len(part) <= 2000 for part in parts)
    # no sentence-ending punctuation lost mid-split
    assert "".join(parts).count(".") == long_text.count(".")


# --- single-paragraph articles as leaves (23 Sep 2026) ---------------------------


class _P:
    def __init__(self, id, citation_id, unit_type, text, heading=None, parent_id=None):
        self.id = id
        self.citation_id = citation_id
        self.unit_type = unit_type
        self.text_content = text
        self.heading = heading
        self.parent_id = parent_id


def test_is_leaf_childless_article_with_a_body_but_not_a_heading_only_container():
    from app.ingestion.chunker import is_leaf

    body = _P(
        1, "art_32", "article", "Where a conformity assessment body ...", "Presumption"
    )
    heading_only = _P(
        2, "art_6", "article", "Classification rules", "Classification rules"
    )
    assert is_leaf(body, has_children=False) is True
    assert is_leaf(heading_only, has_children=True) is False
    assert is_leaf(heading_only, has_children=False) is False  # heading is not a body
    assert (
        is_leaf(_P(3, "art_6.par_1", "paragraph", "text"), has_children=False) is True
    )


def test_chunk_rows_for_a_childless_article_uses_the_article_label_alone():
    from app.ingestion.chunker import chunk_rows_for

    art = _P(
        7,
        "art_32",
        "article",
        "Where a conformity assessment body demonstrates.",
        "Presumption of conformity",
    )
    rows = chunk_rows_for(art, {7: art}, corpus_version_id=1)
    assert len(rows) == 1
    assert rows[0].provision_id == 7 and rows[0].parent_provision_id == 7
    assert rows[0].index_text == (
        "EU AI Act \u2014 Article 32 (Presumption of conformity):\n"
        "Where a conformity assessment body demonstrates."
    )
    assert rows[0].chunk_text == "Where a conformity assessment body demonstrates."


def test_chunk_rows_for_a_paragraph_is_unchanged():
    from app.ingestion.chunker import chunk_rows_for

    art = _P(1, "art_4", "article", "AI literacy", "AI literacy")
    par = _P(
        2, "art_4.par_1", "paragraph", "Providers and deployers shall ...", parent_id=1
    )
    rows = chunk_rows_for(par, {1: art, 2: par}, corpus_version_id=1)
    assert rows[0].index_text.startswith(
        "EU AI Act \u2014 Article 4 (AI literacy), paragraph 1:\n"
    )


def test_citation_label_renders_sectioned_annex_ids():
    from app.ingestion.chunker import citation_label

    assert citation_label("anx_I.sec_A.pt_2") == "Annex I, Section A, point 2"
    assert citation_label("anx_I.sec_B") == "Annex I, Section B"
    assert citation_label("anx_III.pt_5.sub_b") == "Annex III, point 5(b)"  # unchanged


def test_chunk_rows_for_a_sectioned_annex_point_carries_the_section_heading():
    from app.ingestion.chunker import chunk_rows_for

    annex = _P(
        1,
        "anx_I",
        "annex",
        "List of Union harmonisation legislation",
        "List of Union harmonisation legislation",
    )
    sec = _P(
        2,
        "anx_I.sec_A",
        "annex_section",
        "List of Union harmonisation legislation based on the New Legislative Framework",
        "List of Union harmonisation legislation based on the New Legislative Framework",
        parent_id=1,
    )
    pt = _P(
        3,
        "anx_I.sec_A.pt_4",
        "annex_point",
        "Directive 2014/33/EU ... lifts and safety components for lifts",
        parent_id=2,
    )
    rows = chunk_rows_for(pt, {1: annex, 2: sec, 3: pt}, corpus_version_id=1)
    assert len(rows) == 1 and rows[0].parent_provision_id == 1
    assert rows[0].index_text.startswith(
        "EU AI Act \u2014 Annex I (List of Union harmonisation legislation), "
        "Section A (List of Union harmonisation legislation based on the New Legislative Framework), point 4:\n"
        "Directive 2014/33/EU"
    )
    deleted = _P(4, "anx_I.sec_A.pt_1", "annex_point", "", parent_id=2)
    assert (
        chunk_rows_for(deleted, {1: annex, 2: sec, 4: deleted}, corpus_version_id=1)
        == []
    )
