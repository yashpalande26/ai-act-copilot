"""Stage 2: the retrieval grader and its graph node. Zero paid calls: the
grader's extractor, retrieval and the chat client are faked. What is
asserted: proceed reorders and drops nothing; widen happens at most once and
only in-corpus (a second retrieve_step call with the wider breadth, never a
third); abstain happens before any gpt-4o call; grader failure serves the
slice as retrieved; the tags land on the trace; the node is inert when off."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app import config
from app.extraction.llm import FakeExtractor
from app.generation import answer as answer_module
from app.generation import grade as grade_module
from app.generation import graph as graph_module
from app.generation.answer import ABSTENTION_TEXT, RetrievalStep
from app.generation.grade import GradeOutput, PassageGrade, grade_context, reorder
from app.retrieval.search import FusedResult, SearchResult


def _sr(chunk_id, citation_id="art_1"):
    return SearchResult(
        chunk_id=chunk_id,
        citation_id=citation_id,
        citation_label=citation_id,
        chunk_text=f"text {chunk_id}",
        similarity=0.5,
        article_heading=None,
    )


def _fr(chunk_id, **kw):
    return FusedResult(
        result=_sr(chunk_id, **kw), rrf_score=0.01, vector_rank=0, lexical_rank=None
    )


def _grades(*relevant, n=3):
    return GradeOutput(
        grades=[PassageGrade(index=i, relevant=i in relevant) for i in range(n)]
    )


# --- grader ------------------------------------------------------------------


def test_grade_context_returns_valid_relevant_indexes_only():
    out = GradeOutput(
        grades=[
            PassageGrade(index=2, relevant=True),
            PassageGrade(index=0, relevant=False),
            PassageGrade(index=7, relevant=True),  # out of range: ignored
            PassageGrade(index=1, relevant=True),
        ]
    )
    res = grade_context("q", [_fr(1), _fr(2), _fr(3)], extractor=FakeExtractor(out))
    assert res.relevant == (1, 2) and res.ok and res.attempted


def test_grade_context_fails_open_on_refusal_or_exception():
    res = grade_context("q", [_fr(1)], extractor=FakeExtractor(None, refusal="no"))
    assert res.ok is False and res.attempted is True and res.relevant == ()

    class Boom:
        name = "boom"

        def extract(self, **kw):
            raise RuntimeError("down")

    res = grade_context("q", [_fr(1)], extractor=Boom())
    assert res.ok is False and res.relevant == ()
    assert grade_context("q", [], extractor=Boom()).attempted is False


def test_grade_prompt_numbers_every_passage_and_has_no_em_dash():
    text = grade_module._prompt(
        "what?", [_fr(1, citation_id="art_5"), _fr(2, citation_id="art_6")]
    )
    assert (
        "[0] art_5" in text
        and "[1] art_6" in text
        and text.startswith("Question: what?")
    )
    assert "—" not in grade_module.SYSTEM_PROMPT + text
    assert "Do not answer the question" in grade_module.SYSTEM_PROMPT


def test_reorder_puts_relevant_first_and_keeps_everything():
    fused = [_fr(1), _fr(2), _fr(3), _fr(4)]
    out = reorder(fused, (1, 3))
    assert [f.result.chunk_id for f in out] == [2, 4, 1, 3]
    assert reorder(fused, ()) == fused


# --- node --------------------------------------------------------------------


def _session():
    session = MagicMock()
    added = []

    def fake_add(obj):
        added.append(obj)
        if getattr(obj, "id", 1) is None:
            obj.id = uuid4()

    session.add.side_effect = fake_add
    session.added = added
    session.execute.return_value.scalar_one.return_value = uuid4()
    return session


def _run(
    monkeypatch,
    *,
    grades,
    first_slice,
    wider_slice=None,
    llm_text="An answer.",
    on=True,
):
    """One graph turn with the grader on. `grades` is a list of GradeOutput
    (or None for a failure) consumed per grade call; `first_slice` and
    `wider_slice` are what retrieve_step returns on its first and second
    call. Returns (result, trace, calls)."""
    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("AGENTIC_REWRITE", "0")
    monkeypatch.setenv("AGENTIC_GRADE", "1" if on else "0")
    monkeypatch.setenv("AGENTIC_VERIFY", "0")
    monkeypatch.setenv("AGENTIC_DECOMPOSE", "0")
    outputs = iter(grades)
    grade_calls = []

    def fake_grade(query, fused, extractor=None):
        grade_calls.append([f.result.chunk_id for f in fused])
        return grade_context(query, fused, extractor=FakeExtractor(next(outputs)))

    monkeypatch.setattr(graph_module, "grade_context", fake_grade)
    retrieve_calls = []
    slices = iter([first_slice, wider_slice])

    def fake_retrieve(session, query, cv, **kw):
        retrieve_calls.append(kw)
        fused = next(slices)
        return RetrievalStep(
            all_fused=fused,
            fused=fused[: kw["final_context_size"]],
            retrieval_config="hybrid_bm25|actor=none",
            latency_ms=1,
        )

    monkeypatch.setattr(answer_module, "retrieve_step", fake_retrieve)
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = llm_text
    client.chat.completions.create.return_value.usage.prompt_tokens = 10
    client.chat.completions.create.return_value.usage.completion_tokens = 2
    monkeypatch.setattr(answer_module, "_get_client", lambda: client)
    session = _session()
    result = answer_module.generate_grounded_answer(
        session,
        "what must providers do?",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        final_context_size=3,
    )
    from app.db.models import QueryTrace

    trace = next(o for o in session.added if isinstance(o, QueryTrace))
    return (
        result,
        trace,
        {
            "grade": grade_calls,
            "retrieve": retrieve_calls,
            "llm": client.chat.completions.create,
        },
    )


def test_proceed_reorders_relevant_first_drops_nothing_and_tags(monkeypatch):
    slice_ = [
        _fr(1, citation_id="a"),
        _fr(2, citation_id="b"),
        _fr(3, citation_id="gold"),
    ]
    result, trace, calls = _run(monkeypatch, grades=[_grades(2)], first_slice=slice_)
    assert [c.citation_id for c in result.citations] == ["gold", "a", "b"]
    assert len(calls["retrieve"]) == 1 and len(calls["grade"]) == 1
    assert trace.retrieval_config == "hybrid_bm25|actor=none|grade=proceed|path=graph"
    prompt = calls["llm"].call_args.kwargs["messages"][1]["content"]
    assert prompt.index("[gold]") < prompt.index("[a]")


def test_widen_is_exactly_one_in_corpus_re_retrieval_then_proceed(monkeypatch):
    first = [_fr(1), _fr(2), _fr(3)]
    wider = [_fr(1), _fr(2), _fr(3), _fr(4), _fr(9, citation_id="gold"), _fr(6)]
    result, trace, calls = _run(
        monkeypatch,
        grades=[_grades(n=3), _grades(4, n=6)],
        first_slice=first,
        wider_slice=wider,
    )
    assert len(calls["retrieve"]) == 2
    assert calls["retrieve"][1]["breadth"] == grade_module.WIDEN_BREADTH
    assert calls["retrieve"][1]["final_context_size"] == grade_module.WIDEN_SLICE
    assert calls["grade"] == [[1, 2, 3], [1, 2, 3, 4, 9, 6]]
    # served context: relevant first, capped at the normal size (3)
    assert [c.citation_id for c in result.citations] == ["gold", "art_1", "art_1"]
    assert trace.retrieval_config.endswith("|grade=widened|path=graph")
    assert calls["llm"].call_count == 1


def test_nothing_relevant_after_widen_abstains_before_the_model(monkeypatch):
    first = [_fr(1), _fr(2), _fr(3)]
    wider = [_fr(1), _fr(2), _fr(3), _fr(4)]
    result, trace, calls = _run(
        monkeypatch,
        grades=[_grades(n=3), _grades(n=4)],
        first_slice=first,
        wider_slice=wider,
    )
    assert result.answer == ABSTENTION_TEXT and result.citations == []
    assert calls["llm"].call_count == 0
    assert len(calls["retrieve"]) == 2  # never a third
    assert trace.abstained is True
    assert trace.retrieval_config.endswith("|grade=abstain|path=graph")
    assert trace.prompt_tokens is None  # no gpt-4o spend


def test_grader_failure_serves_the_slice_as_retrieved(monkeypatch):
    slice_ = [_fr(1, citation_id="a"), _fr(2, citation_id="b"), _fr(3, citation_id="c")]
    result, trace, calls = _run(monkeypatch, grades=[None], first_slice=slice_)
    assert [c.citation_id for c in result.citations] == ["a", "b", "c"]
    assert len(calls["retrieve"]) == 1
    assert trace.retrieval_config.endswith("|grade=skipped|path=graph")


def test_grader_failure_on_the_widen_serves_the_original_slice(monkeypatch):
    first = [_fr(1, citation_id="a"), _fr(2, citation_id="b"), _fr(3, citation_id="c")]
    wider = [_fr(1), _fr(2), _fr(3), _fr(4)]
    result, trace, _calls = _run(
        monkeypatch, grades=[_grades(n=3), None], first_slice=first, wider_slice=wider
    )
    assert [c.citation_id for c in result.citations] == ["a", "b", "c"]
    assert trace.retrieval_config.endswith("|grade=skipped|path=graph")


def test_grade_node_is_inert_when_off(monkeypatch):
    slice_ = [_fr(1, citation_id="a"), _fr(2, citation_id="b"), _fr(3, citation_id="c")]
    result, trace, calls = _run(monkeypatch, grades=[], first_slice=slice_, on=False)
    assert [c.citation_id for c in result.citations] == ["a", "b", "c"]
    assert calls["grade"] == [] and "grade=" not in trace.retrieval_config
    assert config.agentic_grade_enabled() is False


def test_graph_has_no_node_or_edge_outside_the_corpus():
    g = graph_module.GRAPH.get_graph()
    assert sorted(n for n in g.nodes if not n.startswith("__")) == [
        "decide",
        "decompose",
        "generate",
        "grade",
        "retrieve",
        "rewrite",
        "verify",
    ]
    edges = {(e.source, e.target) for e in g.edges}
    assert edges == {
        ("__start__", "rewrite"),
        ("rewrite", "decompose"),
        ("rewrite", "decide"),
        ("decompose", "retrieve"),
        ("retrieve", "grade"),
        ("retrieve", "decide"),
        ("grade", "generate"),
        ("grade", "decide"),
        ("generate", "verify"),
        ("verify", "decide"),
        ("decide", "__end__"),
    }
    # bounded: no edge returns to retrieve or grade
    assert not any(
        t in ("decompose", "retrieve", "grade")
        and s in ("grade", "generate", "verify", "decide")
        for s, t in edges
    )


def test_widen_constants_are_wider_than_the_defaults():
    assert grade_module.WIDEN_BREADTH > answer_module.RETRIEVAL_CANDIDATE_BREADTH
    assert grade_module.WIDEN_SLICE > 15


@pytest.mark.parametrize("breadth", [25, 50])
def test_breadth_reaches_both_legs_and_the_fusion(monkeypatch, breadth):
    seen = {}
    monkeypatch.setattr(
        answer_module,
        "vector_search",
        lambda s, q, cv, top_k, min_similarity: seen.setdefault("v", top_k) and [],
    )
    monkeypatch.setattr(answer_module, "load_index", lambda cv: object())
    monkeypatch.setattr(
        answer_module,
        "bm25_search",
        lambda s, q, cv, top_k: seen.setdefault("b", top_k) and [],
    )
    monkeypatch.setattr(
        answer_module,
        "rrf_rank_and_fuse",
        lambda v, l, **kw: seen.setdefault("k", kw["top_k"]) and [],
    )
    answer_module.retrieve_candidates(
        object(), "q", 1, breadth=breadth, dense_anchor_floor=None
    )
    assert seen == {"v": breadth, "b": breadth, "k": breadth}
