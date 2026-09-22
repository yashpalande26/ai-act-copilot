"""Stage 4: bounded decomposition. Zero paid calls. What is asserted:
detection fires on every multi_hop item of the agentic set and on nothing
else; the planner is capped, guarded and falls back to the deterministic
split; the interleave keeps every part's share; in the graph each part is
retrieved at most twice (one widen), the union goes to one generation whose
prompt groups passages by part, an exhausted part abstains, the grade node
does not re-grade the union, single-part questions never reach the planner,
the node is inert when off, and the graph has no loop."""

import json
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app import config
from app.db.models import QueryTrace
from app.extraction.llm import FakeExtractor
from app.generation import answer as answer_module
from app.generation import decompose as decompose_module
from app.generation import graph as graph_module
from app.generation.answer import ABSTENTION_TEXT, RetrievalStep
from app.generation.decompose import (
    MAX_SUB_QUERIES,
    DecomposeOutput,
    Plan,
    interleave,
    is_compositional,
    plan,
    split_at_conjunction,
)
from app.generation.grade import GradeOutput, PassageGrade
from app.retrieval.search import FusedResult, SearchResult

SET = json.loads(
    (Path(__file__).resolve().parents[1] / "evals" / "agentic_set.json").read_text()
)


def _fr(chunk_id, cid="art_1"):
    return FusedResult(
        result=SearchResult(
            chunk_id=chunk_id,
            citation_id=cid,
            citation_label=cid,
            chunk_text=f"text {chunk_id}",
            similarity=0.5,
            article_heading=None,
        ),
        rrf_score=0.01,
        vector_rank=0,
        lexical_rank=None,
    )


# --- detection ------------------------------------------------------------------


def test_detection_fires_on_every_multi_hop_item_and_nothing_else():
    fired = {i["id"] for i in SET if is_compositional(i["question"])}
    assert fired == {i["id"] for i in SET if i["bucket"] == "multi_hop"}


def test_detection_edge_cases():
    assert is_compositional("Who is a provider, and what must providers do?")
    assert not is_compositional("What must providers and deployers do?")
    assert not is_compositional(
        "And what else has to be on it?"
    )  # a follow-up, no first clause
    assert not is_compositional("what is a high-risk AI system?")
    assert split_at_conjunction("Who is a provider, and what must providers do?") == [
        "Who is a provider?",
        "What must providers do?",
    ]
    assert split_at_conjunction("what is a provider?") == []


# --- planner ----------------------------------------------------------------------

Q = "Who counts as a deployer under the Act, and what human oversight must deployers of high-risk AI systems assign?"


def test_single_part_question_never_calls_the_planner():
    class Boom:
        name = "boom"

        def extract(self, **kw):
            raise AssertionError("planner must not be called")

    p = plan("what is a high-risk AI system?", extractor=Boom())
    assert p.sub_queries == () and p.source == "none" and p.attempted is False


def test_planner_output_is_guarded_and_capped():
    out = DecomposeOutput(
        sub_queries=[
            "Who counts as a deployer under the Act?",
            "What human oversight must deployers of high-risk AI systems assign?",
            "What must notified bodies verify?",  # entity the question never named: dropped
            "Who counts as a deployer under the Act?",  # duplicate: dropped
            "What is a deployer?",
            "What oversight applies?",
        ]
    )
    p = plan(Q, extractor=FakeExtractor(out))
    assert p.source == "planner"
    assert len(p.sub_queries) == MAX_SUB_QUERIES == 3
    assert p.dropped == ("What must notified bodies verify?",)
    assert "What must notified bodies verify?" not in p.sub_queries


def test_planner_failure_or_thin_output_falls_back_to_the_split():
    p = plan(Q, extractor=FakeExtractor(None, refusal="no"))
    assert p.source == "split" and len(p.sub_queries) == 2 and p.attempted
    p = plan(Q, extractor=FakeExtractor(DecomposeOutput(sub_queries=["only one"])))
    assert p.source == "split"

    class Boom:
        name = "boom"

        def extract(self, **kw):
            raise RuntimeError("down")

    p = plan(Q, extractor=Boom())
    assert p.source == "split" and p.attempted


def test_interleave_keeps_every_parts_share_and_dedupes():
    a = [_fr(1), _fr(2), _fr(3), _fr(4)]
    b = [_fr(2), _fr(5), _fr(6)]
    assert [f.result.chunk_id for f in interleave([a, b], 5)] == [1, 2, 5, 3, 6]
    assert [f.result.chunk_id for f in interleave([a, b], 2)] == [1, 2]
    assert interleave([[], []], 5) == []


# --- graph node -------------------------------------------------------------------


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


def _grades(n, *relevant):
    return GradeOutput(
        grades=[PassageGrade(index=i, relevant=i in relevant) for i in range(n)]
    )


def _run(
    monkeypatch,
    *,
    question,
    plan_result,
    slices,
    grades,
    llm_text="Composed answer.",
    on=True,
):
    """`slices` maps a sub-query to the list of slices its successive
    retrieve_step calls return; `grades` maps a sub-query to successive
    GradeOutputs. Returns (result, trace, calls)."""
    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("AGENTIC_REWRITE", "0")
    monkeypatch.setenv("AGENTIC_GRADE", "1")
    monkeypatch.setenv("AGENTIC_VERIFY", "0")
    monkeypatch.setenv("AGENTIC_DECOMPOSE", "1" if on else "0")
    monkeypatch.setenv("QUERY_UNDERSTANDING", "0")
    monkeypatch.setenv("INTENT_GATE", "0")
    monkeypatch.setenv("CLARIFY_FOLLOWUP", "0")
    monkeypatch.setattr(graph_module, "plan_decomposition", lambda q: plan_result)
    retrieve_calls = []
    grade_calls = []
    slice_iters = {k: iter(v) for k, v in slices.items()}
    grade_iters = {k: iter(v) for k, v in grades.items()}

    def fake_retrieve(session, query, cv, **kw):
        retrieve_calls.append((query, kw.get("breadth")))
        fused = next(slice_iters[query])
        return RetrievalStep(
            all_fused=fused,
            fused=fused[: kw["final_context_size"]],
            retrieval_config="hybrid_bm25|actor=none",
            latency_ms=1,
        )

    def fake_grade(query, fused, extractor=None):
        grade_calls.append(query)
        from app.generation.grade import grade_context

        return grade_context(
            query, fused, extractor=FakeExtractor(next(grade_iters[query]))
        )

    monkeypatch.setattr(answer_module, "retrieve_step", fake_retrieve)
    monkeypatch.setattr(graph_module, "grade_context", fake_grade)
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = llm_text
    client.chat.completions.create.return_value.usage.prompt_tokens = 10
    client.chat.completions.create.return_value.usage.completion_tokens = 2
    monkeypatch.setattr(answer_module, "_get_client", lambda: client)
    session = _session()
    result = answer_module.generate_grounded_answer(
        session,
        question,
        corpus_version_id=1,
        chat_session_id=uuid4(),
        final_context_size=4,
    )
    trace = next(o for o in session.added if isinstance(o, QueryTrace))
    return (
        result,
        trace,
        {
            "retrieve": retrieve_calls,
            "grade": grade_calls,
            "llm": client.chat.completions.create,
        },
    )


SQ1, SQ2 = (
    "Who counts as a deployer under the Act?",
    "What human oversight must deployers assign?",
)
PLAN = Plan(sub_queries=(SQ1, SQ2), source="planner", attempted=True)


def test_parts_are_retrieved_and_graded_separately_then_composed_once(monkeypatch):
    result, trace, calls = _run(
        monkeypatch,
        question=Q,
        plan_result=PLAN,
        slices={
            SQ1: [[_fr(1, "art_3.pt_4"), _fr(2, "art_9")]],
            SQ2: [[_fr(3, "art_26.par_2"), _fr(4, "art_14")]],
        },
        grades={SQ1: [_grades(2, 0)], SQ2: [_grades(2, 0)]},
    )
    assert [q for q, _ in calls["retrieve"]] == [
        SQ1,
        SQ2,
    ]  # one retrieval each, no widen
    assert calls["grade"] == [SQ1, SQ2]  # graded per part, union NOT re-graded
    assert calls["llm"].call_count == 1  # one composed generation
    prompt = calls["llm"].call_args.kwargs["messages"][1]["content"]
    assert (
        f"Context for part 1 ({SQ1})" in prompt
        and f"Context for part 2 ({SQ2})" in prompt
    )
    assert prompt.rstrip().endswith(f"Question: {Q}")
    assert (
        calls["llm"].call_args.kwargs["messages"][0]["content"]
        == answer_module.SYSTEM_PROMPT
    )
    # union context, interleaved, each part's relevant passage first
    assert [c.citation_id for c in result.citations] == [
        "art_3.pt_4",
        "art_26.par_2",
        "art_9",
        "art_14",
    ]
    assert trace.retrieval_config == "hybrid_bm25|decompose=applied:2|path=graph"


def test_a_part_is_widened_at_most_once_then_exhaustion_abstains(monkeypatch):
    result, trace, calls = _run(
        monkeypatch,
        question=Q,
        plan_result=PLAN,
        slices={
            SQ1: [[_fr(1, "art_3.pt_4")]],
            SQ2: [[_fr(3), _fr(4)], [_fr(3), _fr(4), _fr(5), _fr(6)]],
        },
        grades={
            SQ1: [_grades(1, 0)],
            SQ2: [_grades(2), _grades(4)],
        },  # part 2: nothing relevant, twice
    )
    part2 = [b for q, b in calls["retrieve"] if q == SQ2]
    assert part2 == [
        None,
        graph_module.WIDEN_BREADTH,
    ]  # exactly one widen, no third attempt
    assert len([q for q, _ in calls["retrieve"] if q == SQ1]) == 1
    assert result.answer == ABSTENTION_TEXT and result.citations == []
    assert calls["llm"].call_count == 0
    assert trace.abstained is True
    assert (
        trace.retrieval_config
        == "hybrid_bm25|decompose=applied:2|abstain=part_exhausted|path=graph"
    )


def test_a_widened_part_that_recovers_is_composed(monkeypatch):
    result, trace, calls = _run(
        monkeypatch,
        question=Q,
        plan_result=PLAN,
        slices={
            SQ1: [[_fr(1, "art_3.pt_4")]],
            SQ2: [[_fr(3), _fr(4)], [_fr(3), _fr(4), _fr(9, "art_26.par_2")]],
        },
        grades={SQ1: [_grades(1, 0)], SQ2: [_grades(2), _grades(3, 2)]},
    )
    assert len(calls["retrieve"]) == 3 and calls["llm"].call_count == 1
    assert "art_26.par_2" in [c.citation_id for c in result.citations]
    assert trace.retrieval_config.endswith("|decompose=applied:2|path=graph")


def test_sub_query_cap_holds_in_the_graph(monkeypatch):
    many = tuple(f"sub question {i}?" for i in range(MAX_SUB_QUERIES + 2))
    over = Plan(sub_queries=many[:MAX_SUB_QUERIES], source="planner", attempted=True)
    assert len(over.sub_queries) == MAX_SUB_QUERIES
    _result, trace, calls = _run(
        monkeypatch,
        question=Q,
        plan_result=over,
        slices={sq: [[_fr(i + 1)]] for i, sq in enumerate(over.sub_queries)},
        grades={sq: [_grades(1, 0)] for sq in over.sub_queries},
    )
    assert len(calls["retrieve"]) == MAX_SUB_QUERIES
    assert (
        trace.retrieval_config
        == f"hybrid_bm25|decompose=applied:{MAX_SUB_QUERIES}|path=graph"
    )


def test_single_part_question_bypasses_decomposition_and_is_tagged_skipped(monkeypatch):
    q = "what is a high-risk AI system?"
    _result, trace, calls = _run(
        monkeypatch,
        question=q,
        plan_result=Plan(sub_queries=(), source="none"),
        slices={q: [[_fr(1, "art_6")]]},
        grades={q: [_grades(1, 0)]},
    )
    assert [x for x, _ in calls["retrieve"]] == [q] and calls["grade"] == [q]
    assert (
        trace.retrieval_config
        == "hybrid_bm25|actor=none|grade=proceed|decompose=skipped|path=graph".replace(
            "|grade=proceed|decompose=skipped", "|decompose=skipped|grade=proceed"
        )
    )


def test_decompose_node_is_inert_when_off(monkeypatch):
    called = []
    monkeypatch.setattr(decompose_module, "plan", lambda *a, **kw: called.append(a))
    _result, trace, calls = _run(
        monkeypatch,
        question=Q,
        plan_result=PLAN,
        slices={Q: [[_fr(1)]]},
        grades={Q: [_grades(1, 0)]},
        on=False,
    )
    assert [x for x, _ in calls["retrieve"]] == [Q]
    assert "decompose" not in trace.retrieval_config
    assert config.agentic_decompose_enabled() is False


def test_graph_has_no_loop_and_decompose_sits_between_rewrite_and_retrieve():
    g = graph_module.GRAPH.get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    assert ("understand", "decompose") in edges and ("decompose", "retrieve") in edges
    assert not any(
        t in ("rewrite", "understand", "decompose", "retrieve")
        for s, t in edges
        if s in ("retrieve", "grade", "generate", "verify", "decide")
    )


@pytest.mark.parametrize(
    "bucket", ["single_hop", "multi_turn", "unanswerable", "reference"]
)
def test_no_non_multi_hop_question_is_compositional(bucket):
    assert not any(
        is_compositional(i["question"]) for i in SET if i["bucket"] == bucket
    )
