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
