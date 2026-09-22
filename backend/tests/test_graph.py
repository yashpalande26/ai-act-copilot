"""Stage 0 equivalence: with AGENTIC_RAG=1 the LangGraph graph must produce
the same answer, the same citations, the same persisted rows, the same LLM
request and the same trace as the plain path, for all three outcomes (no
context, model abstains, model answers). Zero paid calls: retrieval and the
client are faked exactly as in test_generation.py."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app import config
from app.db.models import Citation, Message, QueryTrace, RetrievalTrace
from app.generation import answer as answer_module
from app.generation import graph as graph_module
from app.generation.answer import ABSTENTION_TEXT
from app.generation.rewrite import RewriteResult
from app.retrieval.search import FusedResult, SearchResult


def _sr(chunk_id, citation_id="art_1", chunk_text="some text"):
    return SearchResult(
        chunk_id=chunk_id,
        citation_id=citation_id,
        citation_label=citation_id,
        chunk_text=chunk_text,
        similarity=0.5,
        article_heading=None,
    )


def _fr(chunk_id, **kwargs):
    return FusedResult(
        result=_sr(chunk_id, **kwargs), rrf_score=0.01, vector_rank=0, lexical_rank=None
    )


def _llm(text):
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = 120
    response.usage.completion_tokens = 30
    return response


def _session():
    session = MagicMock()
    added = []

    def fake_add(obj):
        added.append(obj)
        if isinstance(obj, Message) and obj.id is None:
            obj.id = uuid4()
        if isinstance(obj, QueryTrace) and obj.id is None:
            obj.id = uuid4()

    session.add.side_effect = fake_add
    session.added = added
    session.execute.return_value.scalar_one.return_value = uuid4()
    return session


def _patch_retrieval(monkeypatch, fused):
    monkeypatch.setattr(answer_module, "vector_search", lambda *a, **kw: [])
    monkeypatch.setattr(answer_module, "load_index", lambda cv: object())
    monkeypatch.setattr(answer_module, "bm25_search", lambda *a, **kw: [])
    monkeypatch.setattr(answer_module, "rrf_rank_and_fuse", lambda *a, **kw: fused)


def _run(monkeypatch, *, flag: bool, fused, llm_text):
    """One turn under one flag state. Returns (result, session, llm client)."""
    monkeypatch.setenv("AGENTIC_RAG", "1" if flag else "0")
    monkeypatch.setenv("AGENTIC_REWRITE", "0")  # Stage 0 equivalence: node off
    _patch_retrieval(monkeypatch, fused)
    client = MagicMock()
    client.chat.completions.create.return_value = _llm(llm_text)
    monkeypatch.setattr(answer_module, "_get_client", lambda: client)
    session = _session()
    result = answer_module.generate_grounded_answer(
        session,
        "What must providers do?",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        max_output_tokens=800,
        user_text="what must providers do",
        rewrite=answer_module.RewriteInfo(
            applied=True, prompt_tokens=5, completion_tokens=2
        ),
    )
    return result, session, client


def _shape(session):
    """Persisted rows as comparable tuples, in insertion order."""
    out = []
    for obj in session.added:
        if isinstance(obj, Message):
            out.append(("message", obj.role, obj.content))
        elif isinstance(obj, Citation):
            out.append(
                ("citation", obj.chunk_id, obj.provision_citation_id, obj.quoted_text)
            )
        elif isinstance(obj, QueryTrace):
            out.append(
                (
                    "trace",
                    obj.query_text,
                    obj.answer_text,
                    obj.abstained,
                    obj.model,
                    obj.retrieval_config,
                    obj.prompt_tokens,
                    obj.completion_tokens,
                    obj.rewritten_query,
                    obj.rewrite_prompt_tokens,
                    obj.rewrite_completion_tokens,
                )
            )
        elif isinstance(obj, RetrievalTrace):
            out.append(("rtrace", obj.chunk_id, obj.final_rank, obj.used_in_context))
    return out


def _strip_path_tag(shape):
    return [
        tuple(
            v.replace(graph_module.PATH_TAG, "") if isinstance(v, str) else v
            for v in row
        )
        for row in shape
    ]


SCENARIOS = {
    "no_context": ([], "unused"),
    "model_abstains": ([_fr(1), _fr(2, citation_id="art_2")], ABSTENTION_TEXT),
    "model_answers": (
        [_fr(1, citation_id="art_16.pt_a"), _fr(2, citation_id="art_16.pt_b")],
        "Providers must ensure compliance (Article 16, point (a)).",
    ),
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_graph_reproduces_plain_path(monkeypatch, scenario):
    fused, llm_text = SCENARIOS[scenario]
    off, s_off, c_off = _run(monkeypatch, flag=False, fused=fused, llm_text=llm_text)
    on, s_on, c_on = _run(monkeypatch, flag=True, fused=fused, llm_text=llm_text)

    assert on.answer == off.answer
    assert on.citations == off.citations
    # Same LLM request (or, with no context, no request at all) either way.
    assert (
        c_on.chat.completions.create.call_args_list
        == c_off.chat.completions.create.call_args_list
    )
    if scenario == "no_context":
        assert c_on.chat.completions.create.call_count == 0
    # Same persisted rows in the same order; the only permitted difference is
    # the audit tag on retrieval_config saying the graph served the turn.
    assert _strip_path_tag(_shape(s_on)) == _shape(s_off)
    traces_on = [o for o in s_on.added if isinstance(o, QueryTrace)]
    traces_off = [o for o in s_off.added if isinstance(o, QueryTrace)]
    assert len(traces_on) == len(traces_off) == 1
    assert (
        traces_on[0].retrieval_config
        == traces_off[0].retrieval_config + graph_module.PATH_TAG
    )
    assert graph_module.PATH_TAG not in traces_off[0].retrieval_config
    assert s_on.commit.call_count == s_off.commit.call_count


def test_flag_default_off_and_plain_path_never_imports_the_graph(monkeypatch):
    monkeypatch.delenv("AGENTIC_RAG", raising=False)
    assert config.agentic_rag_enabled() is False
    called = []
    monkeypatch.setattr(
        graph_module, "run_graph", lambda **kw: called.append(kw) or None
    )
    _patch_retrieval(monkeypatch, [])
    answer_module.generate_grounded_answer(
        _session(), "q", corpus_version_id=1, chat_session_id=uuid4()
    )
    assert called == []


def test_flag_on_routes_through_run_graph(monkeypatch):
    monkeypatch.setenv("AGENTIC_RAG", "1")
    seen = {}

    def fake_run_graph(**kw):
        seen.update(kw)
        return answer_module.GroundedAnswer(
            answer=ABSTENTION_TEXT, citations=[], message_id=uuid4()
        )

    monkeypatch.setattr(graph_module, "run_graph", fake_run_graph)
    answer_module.generate_grounded_answer(
        _session(), "q", corpus_version_id=7, chat_session_id=uuid4(), user_text="typed"
    )
    assert seen["query"] == "q" and seen["stored_text"] == "typed"
    assert seen["corpus_version_id"] == 7


def test_graph_shape_is_rewrite_retrieve_generate_decide():
    g = graph_module.GRAPH.get_graph()
    assert sorted(n for n in g.nodes if not n.startswith("__")) == [
        "decide",
        "generate",
        "retrieve",
        "rewrite",
    ]
    edges = {(e.source, e.target) for e in g.edges}
    assert edges == {
        ("__start__", "rewrite"),
        ("rewrite", "retrieve"),
        ("rewrite", "decide"),
        ("retrieve", "generate"),
        ("retrieve", "decide"),
        ("generate", "decide"),
        ("decide", "__end__"),
    }


def test_route_skips_generation_without_context():
    empty = answer_module.RetrievalStep(
        all_fused=[], fused=[], retrieval_config="x", latency_ms=0
    )
    full = answer_module.RetrievalStep(
        all_fused=[_fr(1)], fused=[_fr(1)], retrieval_config="x", latency_ms=0
    )
    assert graph_module.route_after_retrieve({"retrieved": empty}) == "decide"
    assert graph_module.route_after_retrieve({"retrieved": full}) == "generate"


# --- Stage 1: the rewrite node -----------------------------------------------

HISTORY = [
    ("user", "What marking must be affixed to a high-risk AI system?"),
    ("assistant", "Article 16(h) requires providers to affix the CE marking."),
]


def _stage1(monkeypatch, *, history, rewrite_result, fused, llm_text, upstream=None):
    """One graph turn with the node on. rewrite_followup and load_history are
    faked (no gpt-4o-mini call); retrieve_step is recorded so the test can see
    which query retrieval ran on."""
    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("AGENTIC_REWRITE", "1")
    monkeypatch.setattr(graph_module, "load_history", lambda s, cid: history)
    calls = {"rewrite": [], "retrieve": []}

    def fake_rewrite(hist, question, extractor=None):
        calls["rewrite"].append((hist, question))
        return rewrite_result(question)

    monkeypatch.setattr(graph_module, "rewrite_followup", fake_rewrite)
    real_retrieve = answer_module.retrieve_step

    def recording_retrieve(session, query, cv, **kw):
        calls["retrieve"].append(query)
        calls.setdefault("raw", []).append(kw.get("raw_query"))
        return real_retrieve(session, query, cv, **kw)

    monkeypatch.setattr(answer_module, "retrieve_step", recording_retrieve)
    _patch_retrieval(monkeypatch, fused)
    client = MagicMock()
    client.chat.completions.create.return_value = _llm(llm_text)
    monkeypatch.setattr(answer_module, "_get_client", lambda: client)
    session = _session()
    result = answer_module.generate_grounded_answer(
        session,
        "And the penalties for not doing that?",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        user_text="And the penalties for not doing that?",
        rewrite=upstream,
    )
    trace = next(o for o in session.added if isinstance(o, QueryTrace))
    return result, session, client, calls, trace


def _applied(rewritten):
    return lambda q: RewriteResult(
        query=rewritten,
        original=q,
        applied=True,
        attempted=True,
        prompt_tokens=50,
        completion_tokens=12,
    )


def test_actor_conflict_rule():
    # no actor in the original: the rewrite may take the conversation's actor
    assert (
        graph_module.actor_conflict(
            "And the penalties for not doing that?",
            "What are the penalties for providers who do not affix the CE marking?",
        )
        is False
    )
    # same actor either side
    assert (
        graph_module.actor_conflict(
            "and for deployers?", "What must deployers of high-risk AI systems do?"
        )
        is False
    )
    # original names one actor, rewrite names another: ambiguous
    assert (
        graph_module.actor_conflict(
            "and for deployers?", "What must providers of high-risk AI systems do?"
        )
        is True
    )
    # original names one actor, rewrite drops it: ambiguous
    assert (
        graph_module.actor_conflict(
            "and for deployers?", "What must be done for high-risk AI systems?"
        )
        is True
    )


def test_rewrite_node_applies_rewrite_for_retrieval_and_stores_the_original(
    monkeypatch,
):
    rewritten = "What are the penalties for providers who do not affix the CE marking?"
    result, session, client, calls, trace = _stage1(
        monkeypatch,
        history=HISTORY,
        rewrite_result=_applied(rewritten),
        fused=[_fr(1, citation_id="art_99.par_4")],
        llm_text="Fines apply (Article 99, paragraph 4).",
    )
    assert calls["rewrite"] == [(HISTORY, "And the penalties for not doing that?")]
    assert calls["retrieve"] == [rewritten]
    # Stage 1b: the raw follow-up travels with the rewrite so retrieval fuses both
    assert calls["raw"] == ["And the penalties for not doing that?"]
    # the prompt the model saw carries the rewritten question
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert prompt.endswith(f"Question: {rewritten}")
    # the user's own words are what gets stored
    user_msg = next(
        o for o in session.added if isinstance(o, Message) and o.role == "user"
    )
    assert user_msg.content == "And the penalties for not doing that?"
    assert trace.query_text == "And the penalties for not doing that?"
    assert trace.rewritten_query == rewritten
    assert trace.rewrite_prompt_tokens == 50 and trace.rewrite_completion_tokens == 12
    assert trace.retrieval_config.endswith("|rewrite=applied|path=graph")
    assert result.answer.startswith("Fines apply") and result.citations
    assert result.rewritten_query == rewritten


def test_rewrite_node_passes_through_on_turn_one(monkeypatch):
    def not_attempted(q):
        return RewriteResult(query=q, original=q, applied=False, attempted=False)

    _result, _session, _client, calls, trace = _stage1(
        monkeypatch,
        history=[],
        rewrite_result=not_attempted,
        fused=[_fr(1)],
        llm_text="An answer.",
    )
    assert calls["retrieve"] == ["And the penalties for not doing that?"]
    assert trace.rewritten_query is None
    assert trace.retrieval_config.endswith("|path=graph")
    assert "rewrite=" not in trace.retrieval_config


def test_drift_guard_violation_falls_back_to_the_original_and_is_tagged(monkeypatch):
    def guarded(q):
        return RewriteResult(
            query=q,
            original=q,
            applied=False,
            attempted=True,
            introduced=("notified body",),
        )

    _result, _session, _client, calls, trace = _stage1(
        monkeypatch,
        history=HISTORY,
        rewrite_result=guarded,
        fused=[_fr(1)],
        llm_text="An answer.",
    )
    assert calls["retrieve"] == ["And the penalties for not doing that?"]
    assert trace.rewritten_query is None
    assert trace.retrieval_config.endswith("|rewrite=guarded|path=graph")


def test_actor_conflict_abstains_without_retrieval_or_model_call(monkeypatch):
    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("AGENTIC_REWRITE", "1")
    monkeypatch.setattr(graph_module, "load_history", lambda s, cid: HISTORY)
    monkeypatch.setattr(
        graph_module,
        "rewrite_followup",
        lambda h, q, extractor=None: RewriteResult(
            query="What must providers of high-risk AI systems do?",
            original=q,
            applied=True,
            attempted=True,
            prompt_tokens=40,
            completion_tokens=9,
        ),
    )
    retrieve_calls = []
    monkeypatch.setattr(
        answer_module,
        "retrieve_step",
        lambda *a, **kw: retrieve_calls.append(a) or None,
    )
    client = MagicMock()
    monkeypatch.setattr(answer_module, "_get_client", lambda: client)
    session = _session()
    result = answer_module.generate_grounded_answer(
        session, "and for deployers?", corpus_version_id=1, chat_session_id=uuid4()
    )
    assert result.answer == ABSTENTION_TEXT and result.citations == []
    assert retrieve_calls == []
    assert client.chat.completions.create.call_count == 0
    trace = next(o for o in session.added if isinstance(o, QueryTrace))
    assert trace.abstained is True
    assert trace.rewritten_query is None  # not served, so not recorded as served
    assert trace.rewrite_prompt_tokens == 40  # but the spend is
    assert (
        trace.retrieval_config
        == "none|abstain=ambiguous_actor|rewrite=ambiguous|path=graph"
    )
    assert [o for o in session.added if isinstance(o, RetrievalTrace)] == []


def test_rewritten_query_with_no_candidates_abstains_without_retrying_the_original(
    monkeypatch,
):
    rewritten = "What are the penalties for providers who do not affix the CE marking?"
    result, _session, client, calls, trace = _stage1(
        monkeypatch,
        history=HISTORY,
        rewrite_result=_applied(rewritten),
        fused=[],
        llm_text="unused",
    )
    assert result.answer == ABSTENTION_TEXT
    assert calls["retrieve"] == [rewritten]  # once, on the rewrite; no second attempt
    assert client.chat.completions.create.call_count == 0
    assert trace.rewritten_query == rewritten and trace.abstained is True


def test_rewrite_node_skips_when_the_route_already_rewrote(monkeypatch):
    upstream = answer_module.RewriteInfo(
        applied=True, prompt_tokens=1, completion_tokens=1
    )
    _result, _session, _client, calls, _trace = _stage1(
        monkeypatch,
        history=HISTORY,
        rewrite_result=_applied("should not be used"),
        fused=[_fr(1)],
        llm_text="An answer.",
        upstream=upstream,
    )
    assert calls["rewrite"] == []
    assert calls["retrieve"] == ["And the penalties for not doing that?"]


def test_rewrite_node_is_inert_when_its_flag_is_off(monkeypatch):
    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("AGENTIC_REWRITE", "0")
    monkeypatch.setattr(graph_module, "load_history", lambda s, cid: HISTORY)
    called = []
    monkeypatch.setattr(
        graph_module, "rewrite_followup", lambda *a, **kw: called.append(a) or None
    )
    _patch_retrieval(monkeypatch, [])
    answer_module.generate_grounded_answer(
        _session(), "and for deployers?", corpus_version_id=1, chat_session_id=uuid4()
    )
    assert called == []
    assert config.agentic_rewrite_enabled() is False


# --- Stage 1b: dual retrieval -------------------------------------------------


def _f(chunk_id, score, v=None, lx=None, cid="art_1"):
    return FusedResult(
        result=_sr(chunk_id, citation_id=cid),
        rrf_score=score,
        vector_rank=v,
        lexical_rank=lx,
    )


def test_fuse_query_candidates_sums_scores_and_dedupes_by_chunk():
    first = [_f(1, 0.020, v=0, lx=None), _f(2, 0.015, v=2, lx=5)]
    second = [_f(2, 0.010, v=1, lx=None), _f(3, 0.018, v=0, lx=0)]
    fused = answer_module.fuse_query_candidates(first, second, top_k=25)
    assert [f.result.chunk_id for f in fused] == [2, 1, 3]
    assert fused[0].rrf_score == pytest.approx(0.025)
    assert (fused[0].vector_rank, fused[0].lexical_rank) == (1, 5)  # best rank kept
    assert fused[1].rrf_score == pytest.approx(0.020)
    # inputs are not mutated
    assert first[1].rrf_score == 0.015
    assert (
        answer_module.fuse_query_candidates(first, second, top_k=2)[-1].result.chunk_id
        == 1
    )


def test_retrieve_candidates_dual_fuses_before_the_actor_prior(monkeypatch):
    """The raw follow-up's candidate keeps its place after fusion; the actor
    prior fires on the rewrite; the config says dual."""
    legs = {
        "and the penalties for not doing that?": (
            [
                _f(10, 0.016, v=1, cid="art_99.par_4"),
                _f(11, 0.012, v=2, cid="art_75c.par_5"),
            ],
            [],
            "hybrid_bm25",
        ),
        "what are the penalties for providers not affixing the ce marking?": (
            [
                _f(20, 0.017, v=0, cid="art_48.par_3"),
                _f(11, 0.011, v=3, cid="art_75c.par_5"),
            ],
            [],
            "hybrid_bm25",
        ),
    }
    monkeypatch.setattr(
        answer_module, "_hybrid_candidates", lambda s, q, cv, **kw: legs[q]
    )
    fused, cfg = answer_module.retrieve_candidates_dual(
        object(),
        "and the penalties for not doing that?",
        "what are the penalties for providers not affixing the ce marking?",
        1,
        dense_anchor_floor=None,
    )
    ids = [f.result.chunk_id for f in fused]
    assert set(ids) == {10, 11, 20} and len(ids) == 3  # deduped
    assert ids[0] == 11  # retrieved by both queries: summed score 0.023 leads
    assert cfg == "hybrid_bm25|dual|actor=provider|factor=0.25"


def test_retrieve_candidates_dual_reports_degradation_if_either_query_degraded(
    monkeypatch,
):
    cfgs = iter(["hybrid_bm25", "vector_only_degraded"])
    monkeypatch.setattr(
        answer_module,
        "_hybrid_candidates",
        lambda s, q, cv, **kw: ([_f(1, 0.01, v=0)], [], next(cfgs)),
    )
    _, cfg = answer_module.retrieve_candidates_dual(
        object(), "a?", "b?", 1, dense_anchor_floor=None
    )
    assert cfg.startswith("vector_only_degraded|dual")


def test_plain_retrieve_step_never_goes_dual(monkeypatch):
    called = []
    monkeypatch.setattr(
        answer_module,
        "retrieve_candidates_dual",
        lambda *a, **kw: called.append(a) or ([], "x"),
    )
    monkeypatch.setattr(
        answer_module, "retrieve_candidates", lambda *a, **kw: ([], "plain")
    )
    step = answer_module.retrieve_step(object(), "q", 1)
    assert step.retrieval_config == "plain" and called == []
    # same query on both sides is not dual either
    step = answer_module.retrieve_step(object(), "q", 1, raw_query="q")
    assert step.retrieval_config == "plain" and called == []
