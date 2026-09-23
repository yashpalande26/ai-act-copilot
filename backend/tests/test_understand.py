"""ADR-21: plain-language system questions. Zero paid calls. What is
asserted: the verdict-leak detector (the hard safety line) on certifying,
hedged and type-level sentences; the understanding call returns search terms
only, capped, and is not applicable on failure or refusal; in the graph an
understood question retrieves on the terms fused with the question, the
generator gets the explain-and-route instruction, the result is flagged and
tagged; a leaking draft is regenerated once with the leak named and a second
leak abstains; a not-applicable question is untouched; the node is inert when
off."""

import re
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app import config
from app.db.models import QueryTrace
from app.extraction.llm import FakeExtractor
from app.generation import answer as answer_module
from app.generation import graph as graph_module
from app.generation import understand
from app.generation.answer import ABSTENTION_TEXT, RetrievalStep
from app.generation.understand import (
    EXPLAIN_AND_ROUTE_INSTRUCTION,
    MAX_TERMS,
    Understanding,
    UnderstandOutput,
    understand_query,
    verdict_leaks,
)
from app.retrieval.search import FusedResult, SearchResult


def _fr(chunk_id, cid="anx_III.pt_5.sub_b"):
    return FusedResult(
        result=SearchResult(
            chunk_id=chunk_id,
            citation_id=cid,
            citation_label=cid,
            chunk_text="AI systems intended to be used to evaluate the creditworthiness of natural persons",
            similarity=0.3,
            article_heading=None,
        ),
        rrf_score=0.01,
        vector_rank=0,
        lexical_rank=None,
    )


# --- the line -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Your system is high-risk under Annex III.",
        "Your model would be classified as high-risk.",
        "This system falls under Annex III, point 5(b).",
        "Your chatbot is not high-risk.",
        "You are a provider and must register the system.",
        "The user's system is prohibited by Article 5.",
        "Your use case counts as credit scoring.",
    ],
)
def test_verdict_leak_detector_catches_certifying_sentences(text):
    assert verdict_leaks(text), text


@pytest.mark.parametrize(
    "text",
    [
        "Whether your system falls within Annex III point 5(b) depends on its intended purpose.",
        "It is not possible to say whether your model is high-risk from this description.",
        "AI systems intended to evaluate creditworthiness are high-risk (Annex III, point 5(b)).",
        "The assessment determines if your system is in scope.",
        "Providers of high-risk AI systems must register (Article 49).",
        "Deployers shall inform natural persons exposed to an emotion recognition system (Article 50, paragraph 3).",
    ],
)
def test_verdict_leak_detector_allows_hedged_and_type_level_statements(text):
    assert verdict_leaks(text) == [], text


# --- understanding -----------------------------------------------------------------


def test_understanding_returns_search_terms_only_capped_and_deduped():
    out = UnderstandOutput(
        describes_ai_system=True,
        search_terms=[
            "creditworthiness evaluation",
            "credit scoring",
            " Credit Scoring ",
            "Annex III point 5",
            "",
            "access to essential private services",
            "financial services",
            "natural persons",
            "consumer credit",
        ],
    )
    u = understand_query(
        "property valuation model for lending, how risky?", extractor=FakeExtractor(out)
    )
    assert u.applies and u.attempted
    assert len(u.search_terms) == MAX_TERMS
    assert u.search_terms[:3] == (
        "creditworthiness evaluation",
        "credit scoring",
        "Annex III point 5",
    )
    assert u.retrieval_query.startswith("creditworthiness evaluation; credit scoring")
    assert (
        not hasattr(UnderstandOutput, "verdict")
        and "risk_level" not in UnderstandOutput.model_fields
    )


def test_questions_in_the_acts_own_vocabulary_are_never_understood_without_a_call():
    class Boom:
        name = "boom"

        def extract(self, **kw):
            raise AssertionError("must not be called")

    for q in [
        "What must providers of high-risk AI systems do?",
        "what are the requirements set out in Section 2?",
        "Which AI practices are prohibited under Article 5?",
        "what are the obligations of deployers?",
        "What are high-risk AI systems intended to be used for in admission to educational institutions?",
    ]:
        u = understand_query(q, extractor=Boom())
        assert u.applies is False and u.attempted is False, q
    # terse follow-ups describe nothing: not applicable without a call
    assert understand_query("And for profiling?", extractor=Boom()).applies is False
    # "the AI Act" in a lay question does not make it a legal-term question
    out2 = UnderstandOutput(
        describes_ai_system=True,
        search_terms=["AI systems intended to interact directly with natural persons"],
    )
    assert understand_query(
        "we're adding a chatbot to our online shop, does the AI Act apply to us?",
        extractor=FakeExtractor(out2),
    ).applies
    # lay phrasing with "high-risk" alone still reaches the model
    out = UnderstandOutput(
        describes_ai_system=True, search_terms=["creditworthiness evaluation"]
    )
    assert understand_query(
        "a fraud-detection model for card payments, is it high-risk?",
        extractor=FakeExtractor(out),
    ).applies


def test_terms_that_repeat_the_questions_own_words_are_dropped():
    out = UnderstandOutput(
        describes_ai_system=True,
        search_terms=[
            "property valuation",
            "bridge lending",
            "creditworthiness evaluation",
            "credit scoring",
        ],
    )
    u = understand_query(
        "I want to build a property valuation model for bridge lending, how risky is it?",
        extractor=FakeExtractor(out),
    )
    assert u.search_terms == ("creditworthiness evaluation", "credit scoring")


def test_understanding_not_applicable_paths():
    q = "a fraud-detection model for card payments, is it risky?"
    off = UnderstandOutput(describes_ai_system=False, search_terms=[])
    assert (
        understand_query(
            "how risky is my pizza oven?", extractor=FakeExtractor(off)
        ).applies
        is False
    )
    # says it applies but gives no usable terms: not applicable
    empty = UnderstandOutput(describes_ai_system=True, search_terms=["", "   "])
    assert understand_query(q, extractor=FakeExtractor(empty)).applies is False
    assert (
        understand_query(q, extractor=FakeExtractor(None, refusal="no")).applies
        is False
    )

    class Boom:
        name = "boom"

        def extract(self, **kw):
            raise RuntimeError("down")

    u = understand_query(q, extractor=Boom())
    assert u.applies is False and u.attempted is True


def test_prompts_have_no_em_dash_and_forbid_verdicts():
    from app.generation import understand

    assert (
        "—" not in understand.SYSTEM_PROMPT and "—" not in EXPLAIN_AND_ROUTE_INSTRUCTION
    )
    assert "never a classification" in understand.SYSTEM_PROMPT
    # ADR-26: the vaguest description is named as a system description
    assert "even when it does not say what the system does" in understand.SYSTEM_PROMPT
    assert (
        "do not state whether the user's own system"
        in EXPLAIN_AND_ROUTE_INSTRUCTION.lower()
    )


# --- graph -----------------------------------------------------------------------


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


def _run(monkeypatch, *, understanding, drafts, on=True):
    monkeypatch.setenv("AGENTIC_RAG", "1")
    for k in (
        "AGENTIC_REWRITE",
        "AGENTIC_GRADE",
        "AGENTIC_VERIFY",
        "AGENTIC_DECOMPOSE",
        "XREF_EXPANSION",
    ):
        monkeypatch.setenv(k, "0")
    monkeypatch.setenv("QUERY_UNDERSTANDING", "1" if on else "0")
    monkeypatch.setenv("INTENT_GATE", "0")
    monkeypatch.setenv("CLARIFY_FOLLOWUP", "0")
    monkeypatch.setattr(graph_module, "understand_query", lambda q: understanding)
    retrieve_calls = []

    def fake_retrieve(session, query, cv, **kw):
        retrieve_calls.append((query, kw.get("raw_query")))
        return RetrievalStep(
            all_fused=[_fr(1)],
            fused=[_fr(1)],
            retrieval_config="hybrid_bm25|actor=none",
            latency_ms=1,
        )

    monkeypatch.setattr(answer_module, "retrieve_step", fake_retrieve)
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
    q = "I want to build a property valuation model for bridge lending, how risky is it?"
    result = answer_module.generate_grounded_answer(
        session, q, corpus_version_id=1, chat_session_id=uuid4(), max_output_tokens=800
    )
    trace = next(o for o in session.added if isinstance(o, QueryTrace))
    return result, trace, retrieve_calls, client.chat.completions.create


APPLIES = Understanding(
    applies=True,
    search_terms=("creditworthiness evaluation", "credit scoring", "Annex III point 5"),
    attempted=True,
)
NA = Understanding(applies=False, attempted=True)
TYPE_LEVEL = "AI systems intended to evaluate the creditworthiness of natural persons are listed in Annex III, point 5(b). Whether a specific system falls within it depends on its intended purpose."


def test_understood_question_retrieves_on_terms_fused_with_the_question_and_explains(
    monkeypatch,
):
    result, trace, retrieves, gen = _run(
        monkeypatch, understanding=APPLIES, drafts=[TYPE_LEVEL]
    )
    assert retrieves == [
        (
            "I want to build a property valuation model for bridge lending, how risky is it?",
            "creditworthiness evaluation; credit scoring; Annex III point 5",
        )
    ]
    prompt = gen.call_args.kwargs["messages"][1]["content"]
    assert EXPLAIN_AND_ROUTE_INSTRUCTION in prompt
    # the user's words are shown; the question asked is the explain question
    assert "The user wrote: I want to build a property valuation model" in prompt
    assert (
        "Question: What do the retrieved provisions say about AI systems or uses of the kind"
        in prompt
    )
    assert gen.call_args.kwargs["messages"][0]["content"] == answer_module.SYSTEM_PROMPT
    assert result.system_description is True and result.answer == TYPE_LEVEL
    assert (
        trace.retrieval_config == "hybrid_bm25|actor=none|understand=applied|path=graph"
    )
    assert gen.call_count == 1


def test_leaking_draft_is_regenerated_once_with_the_leak_named(monkeypatch):
    result, trace, _, gen = _run(
        monkeypatch,
        understanding=APPLIES,
        drafts=["Your system is high-risk under Annex III.", TYPE_LEVEL],
    )
    assert gen.call_count == 2
    second = gen.call_args_list[1].kwargs["messages"][1]["content"]
    assert (
        'stated a conclusion about the user\'s own system: "Your system is high-risk under Annex III"'
        in second
    )
    assert result.answer == TYPE_LEVEL and result.system_description is True
    assert "|leak=regenerated|" in trace.retrieval_config
    assert trace.prompt_tokens == 200  # both drafts' spend


def test_second_leak_abstains_never_a_third_draft(monkeypatch):
    result, trace, _, gen = _run(
        monkeypatch,
        understanding=APPLIES,
        drafts=["Your system is high-risk.", "Your model would be high-risk too."],
    )
    assert gen.call_count == 2
    assert result.answer == ABSTENTION_TEXT and result.citations == []
    assert "|leak=abstained|" in trace.retrieval_config and trace.abstained is True


def test_not_applicable_question_is_untouched_and_tagged(monkeypatch):
    result, trace, retrieves, gen = _run(
        monkeypatch,
        understanding=NA,
        drafts=["An ordinary answer (Article 16, point (a))."],
    )
    assert retrieves[0][1] is None  # no companion query
    assert (
        EXPLAIN_AND_ROUTE_INSTRUCTION
        not in gen.call_args.kwargs["messages"][1]["content"]
    )
    assert result.system_description is False
    assert trace.retrieval_config == "hybrid_bm25|actor=none|understand=n/a|path=graph"


def test_understand_node_is_inert_when_off(monkeypatch):
    called = []
    monkeypatch.setattr(
        graph_module, "understand_query", lambda q: called.append(q) or APPLIES
    )
    result, trace, retrieves, _ = _run(
        monkeypatch, understanding=APPLIES, drafts=["An answer."], on=False
    )
    assert called == [] and retrieves[0][1] is None
    assert (
        "understand" not in trace.retrieval_config
        and result.system_description is False
    )
    assert config.query_understanding_enabled() is False


# --- ADR-27: risk-tier framing ----------------------------------------------------


def test_risk_tier_flag_is_off_by_default_and_lives_inside_agentic_rag(monkeypatch):
    monkeypatch.delenv("RISK_TIER_FRAMING", raising=False)
    monkeypatch.setenv("AGENTIC_RAG", "1")
    assert config.risk_tier_framing_enabled() is (
        config.RISK_TIER_FRAMING_DEFAULT == "1"
    )
    monkeypatch.setenv("RISK_TIER_FRAMING", "1")
    assert config.risk_tier_framing_enabled() is True
    monkeypatch.setenv("AGENTIC_RAG", "0")
    assert config.risk_tier_framing_enabled() is False  # never outside the graph


def test_understand_uses_the_tiered_prompt_and_wider_cap_when_the_flag_is_on(
    monkeypatch,
):
    monkeypatch.setenv("AGENTIC_RAG", "1")
    seen = {}

    class Spy:
        name = "spy"

        def extract(self, *, system_prompt, user_text, schema):
            seen["prompt"] = system_prompt
            from app.extraction.llm import ExtractionOutcome

            return ExtractionOutcome(
                parsed=schema(
                    describes_ai_system=True,
                    search_terms=[f"term {i}" for i in range(10)],
                ),
                refusal=None,
                prompt_tokens=1,
                completion_tokens=1,
                latency_ms=1,
                model="spy",
            )

    monkeypatch.setenv("RISK_TIER_FRAMING", "0")
    u = understand_query(
        "we built a chatbot for our shop, is it regulated?", extractor=Spy()
    )
    assert (
        seen["prompt"] == understand.SYSTEM_PROMPT
        and len(u.search_terms) == understand.MAX_TERMS
    )
    monkeypatch.setenv("RISK_TIER_FRAMING", "1")
    u = understand_query(
        "we built a chatbot for our shop, is it regulated?", extractor=Spy()
    )
    assert seen["prompt"] == understand.SYSTEM_PROMPT_TIERED
    assert len(u.search_terms) == understand.MAX_TERMS_TIERED
    assert understand.explain_instruction() == understand.EXPLAIN_TIERED_INSTRUCTION
    monkeypatch.setenv("RISK_TIER_FRAMING", "0")
    assert understand.explain_instruction() == understand.EXPLAIN_AND_ROUTE_INSTRUCTION


def test_tiered_prompt_and_instruction_name_no_provision_and_keep_the_hard_lines():
    # Principle-based by contract: no Article number, Annex point or citation id
    # in either text; the scope test and the no-verdict line are present.
    ids = re.compile(r"\bArticle\s+\d|\bAnnex\s+[IVX]+\b|\bart_\d|\banx_[IVX]")
    for text in (
        understand.SYSTEM_PROMPT_TIERED,
        understand.EXPLAIN_TIERED_INSTRUCTION,
    ):
        assert ids.search(text) is None, ids.search(text)
        assert "\u2014" not in text
    assert "ADJACENT" in understand.EXPLAIN_TIERED_INSTRUCTION
    assert (
        "do not state whether the user's own system"
        in understand.EXPLAIN_TIERED_INSTRUCTION
    )
    assert (
        "Never cite a label that is not in the context"
        in understand.EXPLAIN_TIERED_INSTRUCTION
    )
    assert "transparency" in understand.SYSTEM_PROMPT_TIERED
