"""Stage 3: the citation verifier and its graph node. Zero paid calls. What is
asserted: the reference parser and the deterministic missing-reference rule
(including the allowance for cross-references a passage itself names); the
verdict logic over a faked extractor (out-of-range indexes never count as
support); the node's four outcomes with exactly one regeneration at most; an
abstention is never verified; failure serves the answer as generated; the
node is inert when off; the graph has no loop."""

from unittest.mock import MagicMock
from uuid import uuid4

from app import config
from app.db.models import QueryTrace
from app.extraction.llm import FakeExtractor
from app.generation import answer as answer_module
from app.generation import graph as graph_module
from app.generation.answer import ABSTENTION_TEXT, RetrievalStep
from app.generation.verify import (
    SYSTEM_PROMPT,
    ClaimCheck,
    VerifyOutput,
    missing_references,
    passage_block,
    references_in,
    regeneration_instruction,
    verify_answer,
)
from app.retrieval.search import FusedResult, SearchResult


def _fr(chunk_id, cid, text="some text", label=None):
    return FusedResult(
        result=SearchResult(
            chunk_id=chunk_id,
            citation_id=cid,
            citation_label=label or cid,
            chunk_text=text,
            similarity=0.5,
            article_heading=None,
        ),
        rrf_score=0.01,
        vector_rank=0,
        lexical_rank=None,
    )


CTX = [
    _fr(1, "art_16.pt_h", "affix the CE marking ... in accordance with Article 48;"),
    _fr(2, "art_99.par_4.pt_a", "obligations of providers pursuant to Article 16;"),
    _fr(3, "anx_III.pt_4.sub_a", "recruitment or selection of natural persons"),
]


# --- references ---------------------------------------------------------------


def test_references_in_parses_the_label_forms_the_model_writes():
    assert references_in("Article 99, paragraph 4, point (a)") == ["art_99.par_4.pt_a"]
    assert references_in("Article 6(2) and Article 5(1)(a)") == [
        "art_5.par_1.pt_a",
        "art_6.par_2",
    ]
    assert references_in("Article 16, point (h); Article 3, point (24)") == [
        "art_16.pt_h",
        "art_3.pt_24",
    ]
    assert references_in("Annex III, point 4(a) and Annex I") == [
        "anx_I",
        "anx_III.pt_4.sub_a",
    ]
    assert references_in("Articles 53 and 54") == [
        "art_53"
    ]  # lenient: only the first is parsed
    assert references_in("no citations here") == []


def test_missing_references_resolves_ancestors_descendants_and_passage_mentions():
    # present as a passage, as an ancestor of a passage, as a descendant
    assert missing_references("Article 16, point (h)", CTX) == []
    assert missing_references("Article 99", CTX) == []
    assert missing_references("Annex III, point 4", CTX) == []
    # named inside a passage's own text (Article 48, Article 16): allowed
    assert missing_references("in accordance with Article 48", CTX) == []
    # neither: missing
    assert missing_references("Article 19, paragraph 1 requires logs", CTX) == [
        "art_19.par_1"
    ]
    assert missing_references("Annex IV applies", CTX) == ["anx_IV"]


def test_passage_block_carries_the_heading_the_retriever_attached():
    # ADR-25: the verifier (gpt-4o) sees that an Annex III passage sits under
    # the high-risk heading; without a heading the block is label and text.
    with_heading = _fr(
        1,
        "anx_III.pt_5.sub_d",
        "emergency healthcare patient triage systems.",
        label="Annex III, point 5(d)",
    )
    with_heading.result.article_heading = (
        "High-risk AI systems referred to in Article 6(2)"
    )
    assert passage_block(3, with_heading) == (
        "[3] Annex III, point 5(d) (High-risk AI systems referred to in Article 6(2))\n"
        "emergency healthcare patient triage systems."
    )
    assert passage_block(0, CTX[0]) == (
        "[0] art_16.pt_h\naffix the CE marking ... in accordance with Article 48;"
    )
    assert "\u2014" not in SYSTEM_PROMPT
    assert config.verify_model() == "openai:gpt-4o"


# --- verdicts -----------------------------------------------------------------


def _out(*claims):
    return VerifyOutput(
        claims=[
            ClaimCheck(claim=c, passage_indexes=i, verdict=v, reason="r")
            for c, i, v in claims
        ]
    )


def test_verify_answer_supported_claims_pass():
    res = verify_answer(
        "x",
        CTX,
        extractor=FakeExtractor(
            _out(("a", [0], "supported"), ("b", [], "no_citation"))
        ),
    )
    assert res.misgrounded is False and res.ok and res.claims_checked == 2


def test_verify_answer_unsupported_or_out_of_range_is_misgrounded():
    res = verify_answer(
        "x",
        CTX,
        extractor=FakeExtractor(
            _out(("a", [0], "supported"), ("b", [1], "unsupported"))
        ),
    )
    assert res.misgrounded is True and res.unsupported_claims == ("b",)
    res = verify_answer(
        "x", CTX, extractor=FakeExtractor(_out(("a", [9], "supported")))
    )
    assert res.misgrounded is True  # "supported" by a passage that does not exist


def test_no_citation_verdict_cannot_excuse_a_claim_naming_an_absent_provision():
    # the claim names Article 48(1), which is not a passage (only mentioned by one)
    res = verify_answer(
        "x",
        CTX,
        extractor=FakeExtractor(
            _out(
                (
                    "The CE marking must be 5 mm high (Article 48, paragraph 1).",
                    [],
                    "no_citation",
                )
            )
        ),
    )
    assert res.misgrounded is True
    # a claim naming a provision that IS a passage keeps the model's verdict
    res = verify_answer(
        "x",
        CTX,
        extractor=FakeExtractor(
            _out(("See Article 16, point (h).", [0], "no_citation"))
        ),
    )
    assert res.misgrounded is False


def test_verify_answer_missing_reference_is_misgrounded_whatever_the_model_says():
    res = verify_answer(
        "Article 19, paragraph 1",
        CTX,
        extractor=FakeExtractor(_out(("a", [0], "supported"))),
    )
    assert res.misgrounded is True and res.missing_references == ("art_19.par_1",)


def test_verify_answer_fails_open_unless_a_reference_is_missing():
    res = verify_answer("x", CTX, extractor=FakeExtractor(None, refusal="no"))
    assert res.ok is False and res.misgrounded is False

    class Boom:
        name = "boom"

        def extract(self, **kw):
            raise RuntimeError("down")

    res = verify_answer("Article 19", CTX, extractor=Boom())
    assert res.ok is False and res.misgrounded is True


def test_regeneration_instruction_names_the_problems_and_adds_no_content():
    res = verify_answer(
        "Article 19",
        CTX,
        extractor=FakeExtractor(_out(("fine is 50m", [1], "unsupported"))),
    )
    text = regeneration_instruction(res)
    assert "art_19" in text and 'the claim "fine is 50m"' in text
    assert "abstention sentence" in text and "—" not in text


# --- node ---------------------------------------------------------------------


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


def _run(monkeypatch, *, verdicts, drafts, on=True):
    """One graph turn. `verdicts` are VerifyResult-producing outputs consumed
    per verify call; `drafts` the answer texts the model returns per call."""
    monkeypatch.setenv("AGENTIC_RAG", "1")
    monkeypatch.setenv("AGENTIC_REWRITE", "0")
    monkeypatch.setenv("AGENTIC_GRADE", "0")
    monkeypatch.setenv("AGENTIC_VERIFY", "1" if on else "0")
    monkeypatch.setenv("AGENTIC_DECOMPOSE", "0")
    outputs = iter(verdicts)
    verify_calls = []

    def fake_verify(answer, fused, extractor=None):
        verify_calls.append(answer)
        return verify_answer(answer, fused, extractor=FakeExtractor(next(outputs)))

    monkeypatch.setattr(graph_module, "verify_answer", fake_verify)
    monkeypatch.setattr(
        answer_module,
        "retrieve_step",
        lambda *a, **kw: RetrievalStep(
            all_fused=CTX,
            fused=CTX,
            retrieval_config="hybrid_bm25|actor=none",
            latency_ms=1,
        ),
    )
    texts = iter(drafts)
    client = MagicMock()

    def create(**kw):
        resp = MagicMock()
        resp.choices[0].message.content = next(texts)
        resp.usage.prompt_tokens = 100
        resp.usage.completion_tokens = 20
        return resp

    client.chat.completions.create.side_effect = create
    monkeypatch.setattr(answer_module, "_get_client", lambda: client)
    session = _session()
    result = answer_module.generate_grounded_answer(
        session,
        "q",
        corpus_version_id=1,
        chat_session_id=uuid4(),
        max_output_tokens=800,
    )
    trace = next(o for o in session.added if isinstance(o, QueryTrace))
    return result, trace, verify_calls, client.chat.completions.create


def test_passed_serves_the_answer_with_one_generation(monkeypatch):
    result, trace, verifies, gen = _run(
        monkeypatch,
        verdicts=[_out(("a", [0], "supported"))],
        drafts=["Good answer (Article 16, point (h))."],
    )
    assert result.answer.startswith("Good answer") and len(result.citations) == 3
    assert gen.call_count == 1 and verifies == ["Good answer (Article 16, point (h))."]
    assert trace.retrieval_config.endswith("|verify=passed|path=graph")
    assert trace.prompt_tokens == 100


def test_regenerated_once_with_grounding_instruction_then_passed(monkeypatch):
    result, trace, verifies, gen = _run(
        monkeypatch,
        verdicts=[
            _out(("fine is 50m", [1], "unsupported")),
            _out(("fine is 15m", [1], "supported")),
        ],
        drafts=["Bad draft.", "Better draft (Article 99, paragraph 4, point (a))."],
    )
    assert result.answer.startswith("Better draft")
    assert gen.call_count == 2
    second_prompt = gen.call_args_list[1].kwargs["messages"][1]["content"]
    assert "A previous draft of this answer was rejected" in second_prompt
    assert 'the claim "fine is 50m"' in second_prompt
    assert (
        gen.call_args_list[1].kwargs["messages"][0]["content"]
        == answer_module.SYSTEM_PROMPT
    )
    assert verifies == [
        "Bad draft.",
        "Better draft (Article 99, paragraph 4, point (a)).",
    ]
    assert trace.retrieval_config.endswith("|verify=regenerated|path=graph")
    assert (
        trace.prompt_tokens == 200 and trace.completion_tokens == 40
    )  # both drafts' spend


def test_still_misgrounded_after_one_regeneration_abstains(monkeypatch):
    result, trace, verifies, gen = _run(
        monkeypatch,
        verdicts=[_out(("a", [1], "unsupported")), _out(("b", [1], "unsupported"))],
        drafts=["Bad draft.", "Still bad."],
    )
    assert result.answer == ABSTENTION_TEXT and result.citations == []
    assert gen.call_count == 2 and len(verifies) == 2  # never a third of either
    assert trace.abstained is True
    assert trace.retrieval_config.endswith("|verify=abstained|path=graph")
    assert trace.prompt_tokens == 200  # the spend is kept on the trace


def test_regenerated_draft_that_abstains_abstains_without_a_second_verify(monkeypatch):
    result, trace, verifies, gen = _run(
        monkeypatch,
        verdicts=[_out(("a", [1], "unsupported"))],
        drafts=["Bad draft.", ABSTENTION_TEXT],
    )
    assert result.answer == ABSTENTION_TEXT
    assert gen.call_count == 2 and len(verifies) == 1
    assert trace.retrieval_config.endswith("|verify=abstained|path=graph")


def test_verifier_failure_serves_the_answer_as_generated(monkeypatch):
    result, trace, _verifies, gen = _run(
        monkeypatch, verdicts=[None], drafts=["Unchecked answer."]
    )
    assert result.answer == "Unchecked answer." and gen.call_count == 1
    assert trace.retrieval_config.endswith("|verify=skipped|path=graph")


def test_an_abstention_is_never_verified(monkeypatch):
    result, trace, verifies, gen = _run(
        monkeypatch, verdicts=[], drafts=[ABSTENTION_TEXT]
    )
    assert result.answer == ABSTENTION_TEXT and verifies == [] and gen.call_count == 1
    assert "verify=" not in trace.retrieval_config


def test_verify_node_is_inert_when_off(monkeypatch):
    result, trace, verifies, _gen = _run(
        monkeypatch, verdicts=[], drafts=["An answer."], on=False
    )
    assert result.answer == "An answer." and verifies == []
    assert "verify=" not in trace.retrieval_config
    assert config.agentic_verify_enabled() is False


def test_graph_edges_have_no_loop_and_verify_sits_between_generate_and_decide():
    g = graph_module.GRAPH.get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    assert ("generate", "verify") in edges and ("verify", "decide") in edges
    assert ("generate", "decide") not in edges
    assert not any(
        t in ("retrieve", "grade", "generate", "verify")
        for s, t in edges
        if s in ("verify", "decide")
    )
