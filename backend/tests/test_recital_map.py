"""ADR-33: the recital-to-provision map. Zero paid calls, no database: the
edge rules and the context selection are pure functions."""

from app import config
from app.retrieval.recital_map import (
    Edge,
    _matches,
    recitals_for_context,
    resolve_to_corpus,
    semantic_choice,
)

IDS = {"art_6", "art_6.par_2", "anx_III", "anx_III.pt_5", "anx_III.pt_5.sub_b"}


def test_resolve_to_corpus_takes_the_most_specific_existing_ancestor():
    assert resolve_to_corpus("art_6.par_2.pt_a", IDS) == "art_6.par_2"
    assert resolve_to_corpus("art_6.par_2", IDS) == "art_6.par_2"
    assert resolve_to_corpus("anx_III.pt_5.sub_b", IDS) == "anx_III.pt_5.sub_b"
    assert resolve_to_corpus("art_99.par_3", IDS) is None


def test_semantic_choice_is_conservative():
    # below the floor: nothing
    assert semantic_choice([("art_5.par_1.pt_c", 0.70), ("art_2", 0.60)]) is None
    # clear winner
    assert semantic_choice(
        [("art_5.par_1.pt_c", 0.809), ("anx_III.pt_5.sub_b", 0.715)]
    ) == ("art_5.par_1.pt_c", 0.809)
    # close siblings: the parent explains both (Recital 58 and Annex III point 5)
    assert semantic_choice(
        [("anx_III.pt_5.sub_a", 0.786), ("anx_III.pt_5.sub_b", 0.784)]
    ) == ("anx_III.pt_5", 0.786)
    # close child and parent: the parent
    assert semantic_choice(
        [("anx_III.pt_5.sub_a", 0.786), ("anx_III.pt_5", 0.780)]
    ) == ("anx_III.pt_5", 0.786)
    # close call between different articles: no edge
    assert semantic_choice([("art_63.par_1", 0.818), ("art_17.par_2", 0.806)]) is None
    # a single neighbour above the floor is taken
    assert semantic_choice([("art_1.par_1", 0.88)]) == ("art_1.par_1", 0.88)


def test_matches_covers_self_descendant_and_direct_parent_only():
    assert _matches(
        "anx_III.pt_5", "anx_III.pt_5.sub_b"
    )  # target is the point, context the sub-point
    assert _matches("art_6", "art_6.par_2")
    assert _matches("art_6.par_1.pt_b", "art_6.par_1")  # context is the direct parent
    assert not _matches(
        "anx_III.pt_4.sub_b", "anx_III.pt_4.sub_a"
    )  # siblings do not match
    assert not _matches("art_6", "art_60")


def test_recitals_for_context_ranks_by_specificity_then_position_and_caps():
    edges = [
        Edge("rec_58", "anx_III.pt_5", "semantic", 0.786),
        Edge("rec_40", "art_5.par_1", "explicit", None),
        Edge("rec_40", "art_16", "explicit", None),
        Edge("rec_40", "art_26.par_10", "explicit", None),
        Edge("rec_40", "art_5.par_2", "explicit", None),
        Edge("rec_31", "art_5.par_1.pt_c", "semantic", 0.809),
        Edge("rec_3", "art_16", "explicit", None),
    ]
    # the creditworthiness case: the point-level semantic edge at position 0 beats a
    # paragraph-level explicit edge at position 1
    ctx = ["anx_III.pt_5.sub_b", "art_5.par_1.pt_c", "art_16.pt_a"]
    assert [r for r, _ in recitals_for_context(edges, ctx, cap=2)] == [
        "rec_58",
        "rec_31",
    ]
    # the social-scoring case: an exact semantic match outranks the broad explicit one
    assert [r for r, _ in recitals_for_context(edges, ["art_5.par_1.pt_c"], cap=2)] == [
        "rec_31",
        "rec_40",
    ]
    # root-level explicit edges still fire when nothing more specific exists
    assert [r for r, _ in recitals_for_context(edges, ["art_16.pt_a"], cap=2)] == [
        "rec_40",
        "rec_3",
    ]
    assert recitals_for_context(edges, ["art_99.par_3"]) == []
    assert (
        recitals_for_context(edges, ["rec_58"]) == []
    )  # a recital never pulls another


def test_cross_cutting_recitals_are_not_candidates():
    edges = [
        Edge("rec_140", t, "explicit", None)
        for t in (
            "art_10",
            "art_22.par_2",
            "art_24.par_2",
            "art_4.par_2",
            "art_5",
            "art_6.par_4",
            "art_9.par_2",
        )
    ]
    edges.append(Edge("rec_38", "art_10", "explicit", None))
    assert [r for r, _ in recitals_for_context(edges, ["art_10.par_2"], cap=2)] == [
        "rec_38"
    ]


def test_recital_map_flag_lives_inside_agentic_rag(monkeypatch):
    monkeypatch.delenv("RECITAL_MAP", raising=False)
    monkeypatch.setenv("AGENTIC_RAG", "1")
    assert config.recital_map_enabled() is (config.RECITAL_MAP_DEFAULT == "1")
    monkeypatch.setenv("RECITAL_MAP", "1")
    assert config.recital_map_enabled() is True
    monkeypatch.setenv("AGENTIC_RAG", "0")
    assert config.recital_map_enabled() is False


# --- attachment into the served context (answer.py) ----------------------


def _fr(chunk_id: int, citation_id: str):
    from app.retrieval.search import FusedResult, SearchResult

    return FusedResult(
        result=SearchResult(
            chunk_id=chunk_id,
            citation_id=citation_id,
            citation_label=citation_id,
            chunk_text="text",
            similarity=0.5,
            article_heading=None,
        ),
        rrf_score=1.0 / chunk_id,
        vector_rank=None,
        lexical_rank=None,
    )


def _fake_map(monkeypatch, edges):
    """The map and the chunk fetch without a database. Recital chunk ids are
    900 + N so the test can tell them from operative chunks."""
    from app.generation import answer
    from app.retrieval import recital_map

    monkeypatch.setattr(recital_map, "edges_for", lambda session, cv: edges)

    def fake_fetch(session, cv, roots):
        return {r: [_fr(900 + int(r[4:]), r).result] for r in roots}

    monkeypatch.setattr(answer, "fetch_provision_chunks", fake_fetch)


def test_attach_is_additive_and_never_evicts_an_operative_chunk(monkeypatch):
    """The cheap run (23 Sep 2026) served Recital 91 without Article 26(6):
    the recital was chosen for a slice that held Article 26(6) at rank 14 and
    then took its place. The recitals go after the operative slice."""
    from app.generation import answer

    _fake_map(monkeypatch, [Edge("rec_91", "art_26", "semantic", 0.8)])
    ops = [_fr(i, f"art_{i}") for i in range(1, 15)] + [_fr(26, "art_26.par_6")]
    beyond = [_fr(50, "art_50"), _fr(51, "art_51")]
    out, tag = answer.attach_mapped_recitals(None, 1, [*ops, *beyond], 15)
    ids = [f.result.citation_id for f in out]
    assert ids[:15] == [f.result.citation_id for f in ops]
    assert ids[15] == "rec_91" and ids[16:] == ["art_50", "art_51"]
    assert tag == "semantic:1"
    assert answer.served_size(out, 15) == 16


def test_refit_drops_a_recital_whose_provision_left_the_slice(monkeypatch):
    """After the grader's cut (the widen path) the operative slice changes;
    the recitals are chosen again for what is actually served."""
    from app.generation import answer

    _fake_map(
        monkeypatch,
        [
            Edge("rec_91", "art_26", "semantic", 0.8),
            Edge("rec_3", "art_16", "explicit", None),
        ],
    )
    # graded order: art_16 relevant first, art_26.par_6 pushed past the cut
    ordered = [
        _fr(16, "art_16"),
        _fr(1, "art_1"),
        _fr(2, "art_2"),
        _fr(26, "art_26.par_6"),
    ]
    stale = [_fr(991, "rec_91"), _fr(903, "rec_3")]  # attached before the cut
    out, served, config = answer.refit_mapped_recitals(
        None,
        1,
        [*ordered, *stale],
        3,
        "hybrid_bm25|recmap=semantic:1,explicit:1|recitals=2|x=1",
    )
    ids = [f.result.citation_id for f in out]
    assert ids[:served] == ["art_16", "art_1", "art_2", "rec_3"]
    assert "rec_91" not in ids
    assert config == "hybrid_bm25|x=1|recmap=explicit:1|recitals=1"


def test_graded_step_refits_after_the_grader_cut(monkeypatch):
    """Graph wiring: a widened slice graded down to the context size keeps
    only the recitals whose provision survived the cut."""
    from app.generation import graph as graph_module
    from app.generation.answer import RetrievalStep
    from app.generation.grade import GradeResult

    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("RECITAL_MAP", "1")
    _fake_map(
        monkeypatch,
        [
            Edge("rec_91", "art_26", "semantic", 0.8),
            Edge("rec_3", "art_16", "explicit", None),
        ],
    )
    wide = [
        _fr(1, "art_1"),
        _fr(26, "art_26.par_6"),
        _fr(2, "art_2"),
        _fr(16, "art_16"),
    ]
    step = RetrievalStep(
        all_fused=[*wide, _fr(991, "rec_91")],
        fused=[*wide, _fr(991, "rec_91")],
        retrieval_config="hybrid_bm25|recmap=semantic:1|recitals=1",
        latency_ms=1,
    )
    state = {
        "final_context_size": 2,
        "session": None,
        "corpus_version_id": 1,
        "query": "why must providers do this?",
    }
    graded = graph_module._graded_step(
        state, step, GradeResult(relevant=(0, 3), attempted=True, ok=True)
    )
    ids = [f.result.citation_id for f in graded.fused]
    assert ids == ["art_1", "art_16", "rec_3"]
    assert "rec_91" not in [f.result.citation_id for f in graded.all_fused]
    assert graded.retrieval_config == "hybrid_bm25|recmap=explicit:1|recitals=1"


def test_decomposed_turns_serve_operative_provisions_only(monkeypatch):
    """The merged context of a decomposed turn drops the per-part recitals:
    the interleave could keep one and cut its provision."""
    from app.generation import graph as graph_module
    from app.generation.answer import RetrievalStep
    from app.generation.decompose import Plan

    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("RECITAL_MAP", "1")
    part_a = [_fr(1, "art_1"), _fr(903, "rec_3")]
    part_b = [_fr(2, "art_2"), _fr(991, "rec_91")]
    slices = iter([part_a, part_b])

    def fake_part(state, sq):
        fused = next(slices)
        return RetrievalStep(
            all_fused=fused, fused=fused, retrieval_config="hybrid_bm25", latency_ms=1
        ), 1

    monkeypatch.setattr(graph_module, "_retrieve_part", fake_part)
    out = graph_module.retrieve(
        {
            "plan": Plan(
                sub_queries=("why is a banned?", "why is b banned?"), source="split"
            ),
            "final_context_size": 15,
        }
    )
    served = [f.result.citation_id for f in out["retrieved"].fused]
    assert served == ["art_1", "art_2"]
    assert all(
        not c.startswith("rec_")
        for _, fs in out["parts"]
        for c in [f.result.citation_id for f in fs]
    )


# --- explanation intent (ADR-34) -------------------------------------------

EXPLANATION = [
    "why is a creditworthiness scoring system treated as high-risk?",
    "why does the AI Act prohibit social scoring?",
    "why is emotion recognition at the workplace banned?",
    "why do people have to be told they are interacting with an AI system?",
    "And why is that?",
    "What is the reason for banning social scoring?",
    "what's the rationale behind Article 5?",
    "how come chatbots must disclose that they are AI?",
    "what is the reasoning behind classifying credit scoring as high-risk?",
]
DIRECT = [
    "what are the penalties?",
    "What are the penalties for not affixing the CE marking to a high-risk AI system?",
    "what does Chapter III require?",
    "For what specific purpose can 'real-time' remote biometric identification systems be deployed?",
    "What is the goal of considering the effects and possible interaction of the requirements?",
    "What action should market surveillance authorities take if they have sufficient reason to consider a model a risk?",
    "what rules apply if we change the intended purpose of the system later?",
    "which article covers reasonably foreseeable misuse?",
    "list the obligations of providers of high-risk AI systems",
    "What characteristics make a model general-purpose in the first place?",
    "who is a provider?",
]


def test_explanation_intent_separates_why_from_direct_lookups():
    from app.retrieval.recital_map import is_explanation_query

    assert [q for q in EXPLANATION if not is_explanation_query(q)] == []
    assert [q for q in DIRECT if is_explanation_query(q)] == []


def test_expansion_applies_only_inside_the_flag_and_only_on_explanation(monkeypatch):
    from app.generation import answer

    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("RECITAL_MAP", "1")
    assert answer.recital_expansion_applies("why is social scoring banned?")
    assert not answer.recital_expansion_applies("what are the penalties?")
    monkeypatch.setenv("RECITAL_MAP", "0")
    assert not answer.recital_expansion_applies("why is social scoring banned?")


def test_graded_step_uses_the_flag_off_path_for_a_direct_query(monkeypatch):
    """A direct question under the flag is ADR-32 exactly: reorder, demote,
    no refit and no map lookup."""
    from app.generation import answer
    from app.generation import graph as graph_module
    from app.generation.answer import RetrievalStep
    from app.generation.grade import GradeResult

    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("RECITAL_MAP", "1")

    def boom(*a, **k):
        raise AssertionError("refit must not run on a direct query")

    monkeypatch.setattr(answer, "refit_mapped_recitals", boom)
    fused = [_fr(991, "rec_91"), _fr(1, "art_1"), _fr(2, "art_2")]
    step = RetrievalStep(
        all_fused=fused, fused=fused, retrieval_config="hybrid_bm25", latency_ms=1
    )
    state = {
        "final_context_size": 3,
        "session": None,
        "corpus_version_id": 1,
        "query": "what are the penalties?",
    }
    graded = graph_module._graded_step(
        state, step, GradeResult(relevant=(0,), attempted=True, ok=True)
    )
    # relevant first (the recital), then demotion keeps the operative head
    assert [f.result.citation_id for f in graded.fused] == ["art_1", "art_2", "rec_91"]


def test_decomposed_turn_strips_recitals_only_for_explanation_parts(monkeypatch):
    from app.generation import graph as graph_module
    from app.generation.answer import RetrievalStep
    from app.generation.decompose import Plan

    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("RECITAL_MAP", "1")
    part_a = [
        _fr(1, "art_1"),
        _fr(903, "rec_3"),
    ]  # explanation part: recital attached by the map
    part_b = [
        _fr(2, "art_2"),
        _fr(991, "rec_91"),
    ]  # direct part: recital came through the pool
    slices = iter([part_a, part_b])

    def fake_part(state, sq):
        fused = next(slices)
        return RetrievalStep(
            all_fused=fused, fused=fused, retrieval_config="hybrid_bm25", latency_ms=1
        ), 1

    monkeypatch.setattr(graph_module, "_retrieve_part", fake_part)
    out = graph_module.retrieve(
        {
            "plan": Plan(
                sub_queries=("why is X banned?", "what are the penalties?"),
                source="split",
            ),
            "final_context_size": 15,
        }
    )
    served = [f.result.citation_id for f in out["retrieved"].fused]
    assert "rec_3" not in served and "rec_91" in served
