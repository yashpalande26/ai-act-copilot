from app.retrieval.actor import (
    ACTOR_MAP,
    ACTOR_MISMATCH_FACTOR,
    actor_for,
    apply_actor_prior,
    detect_query_actor,
)
from app.retrieval.search import FusedResult, SearchResult


def _fr(chunk_id, citation_id, rrf_score):
    return FusedResult(
        result=SearchResult(
            chunk_id=chunk_id,
            citation_id=citation_id,
            citation_label=citation_id,
            chunk_text="text",
            similarity=0.5,
            article_heading=None,
        ),
        rrf_score=rrf_score,
        vector_rank=0,
        lexical_rank=None,
    )


# --- actor_for: the map and its inheritance rule -------------------------


def test_article_level_label_is_inherited_by_points():
    assert actor_for("art_16") == "provider"
    assert actor_for("art_16.pt_a") == "provider"
    assert actor_for("art_27.par_1.pt_c") == "deployer"


def test_article_50_splits_by_paragraph():
    assert actor_for("art_50.par_1") == "provider"
    assert actor_for("art_50.par_2") == "provider"
    assert actor_for("art_50.par_3") == "deployer"
    assert actor_for("art_50.par_4") == "deployer"
    # Applies to both, so it must not inherit anything from art_50.
    assert actor_for("art_50.par_5") is None
    assert actor_for("art_50") is None


def test_heading_keyword_trap_article_13_is_unlabelled():
    # Heading says "information to deployers" but the obligor is the provider.
    assert actor_for("art_13") is None
    assert actor_for("art_13.par_3.pt_d") is None


def test_unmapped_provisions_and_annexes_are_none():
    assert actor_for("art_5.par_1.pt_a") is None
    assert actor_for("anx_III.pt_5.sub_b") is None


def test_map_values_are_a_closed_vocabulary():
    allowed = {
        "provider",
        "deployer",
        "importer",
        "distributor",
        "authorised_representative",
    }
    assert set(ACTOR_MAP.values()) <= allowed


# --- detect_query_actor: fires on exactly one actor ----------------------


def test_single_actor_fires():
    assert (
        detect_query_actor("What must a deployer of a high-risk AI system do?")
        == "deployer"
    )
    assert (
        detect_query_actor("Obligations of PROVIDERS of high-risk AI systems")
        == "provider"
    )


def test_authorised_representative_is_one_family_either_spelling():
    assert detect_query_actor("duties of the authorised representative") == (
        "authorised_representative"
    )
    assert detect_query_actor("duties of authorized representatives") == (
        "authorised_representative"
    )


def test_no_actor_is_none():
    assert (
        detect_query_actor("Which AI practices are prohibited under the EU AI Act?")
        is None
    )


def test_two_actors_is_none():
    assert detect_query_actor("What must providers give to deployers?") is None


def test_word_boundary_prevents_substring_hits():
    # "provided" is not "provider"
    assert detect_query_actor("information provided to the public") is None


# --- apply_actor_prior: advisory re-sort, never a filter ------------------


def test_none_query_actor_is_identity():
    fused = [_fr(1, "art_26.par_1", 0.02), _fr(2, "art_16.pt_a", 0.01)]
    assert apply_actor_prior(fused, None, ACTOR_MISMATCH_FACTOR) == fused


def test_factor_one_is_identity():
    fused = [_fr(1, "art_26.par_1", 0.02), _fr(2, "art_16.pt_a", 0.01)]
    assert apply_actor_prior(fused, "provider", 1.0) == fused


def test_mismatch_sinks_below_match_and_unlabelled_is_untouched():
    deployer_chunk = _fr(1, "art_26.par_1", 0.020)  # mismatch for a provider query
    unlabelled = _fr(2, "art_5.par_1.pt_a", 0.012)
    provider_chunk = _fr(3, "art_16.pt_a", 0.010)  # match
    out = apply_actor_prior(
        [deployer_chunk, unlabelled, provider_chunk], "provider", 0.25
    )
    # 0.020 * 0.25 = 0.005 < 0.010 < 0.012
    assert [f.result.citation_id for f in out] == [
        "art_5.par_1.pt_a",
        "art_16.pt_a",
        "art_26.par_1",
    ]


def test_nothing_is_removed_and_raw_scores_are_preserved():
    fused = [
        _fr(i, cid, s)
        for i, (cid, s) in enumerate(
            [("art_26.par_1", 0.03), ("art_16.pt_a", 0.02), ("art_50.par_5", 0.01)]
        )
    ]
    out = apply_actor_prior(fused, "provider", 0.25)
    assert len(out) == len(fused)
    assert {f.result.chunk_id for f in out} == {f.result.chunk_id for f in fused}
    # rrf_score is left raw; the adjustment lives only in the ordering.
    assert {f.rrf_score for f in out} == {0.03, 0.02, 0.01}


def test_strongly_ranked_mismatch_can_still_lead():
    # The soft factor is the point: a mismatch scored high enough by both legs
    # is NOT suppressed, unlike a hard filter.
    strong_mismatch = _fr(1, "art_26.par_5", 0.100)
    weak_match = _fr(2, "art_16.pt_a", 0.010)
    out = apply_actor_prior([strong_mismatch, weak_match], "provider", 0.25)
    assert out[0].result.citation_id == "art_26.par_5"  # 0.025 > 0.010
