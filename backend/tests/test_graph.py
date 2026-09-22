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


def test_graph_shape_is_retrieve_generate_decide_only():
    g = graph_module.GRAPH.get_graph()
    assert sorted(n for n in g.nodes if not n.startswith("__")) == [
        "decide",
        "generate",
        "retrieve",
    ]
    edges = {(e.source, e.target) for e in g.edges}
    assert edges == {
        ("__start__", "retrieve"),
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
