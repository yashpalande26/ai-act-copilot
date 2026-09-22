"""The grounded-answer pipeline as a LangGraph graph, behind AGENTIC_RAG=1
(default off).

    START -> rewrite -> retrieve -> grade -> generate -> verify -> decide -> END
    (retrieve -> decide directly when there is no context: the model is not
    called and decide abstains, exactly as the plain path does;
    rewrite -> decide directly on an actor conflict; grade -> decide when
    nothing relevant remains after its one widen: see below)

Stage 0 (22 Sep 2026): retrieve, generate and decide call the step function
of the same name in app.generation.answer and nothing else, so the graph is a
different EXECUTION of the same code, not a second implementation.

Stage 1 (22 Sep 2026): the rewrite node, active only when
config.agentic_rewrite_enabled() (AGENTIC_REWRITE, effective inside the graph
only). It reuses app.generation.rewrite unchanged:

  turn 2+ only      no history in the chat -> no model call, pass-through
  idempotent        an already-standalone question passes through unchanged
  drift guard       a rewrite naming an actor, body, system type, article,
                    annex or number absent from the conversation is discarded
                    and the original question is used (rewrite.introduced_entities)
  actor conflict    the deterministic actor detector is run on the original
                    and on the rewrite; when the original names one actor and
                    the rewrite names a different one or none, the coreference
                    is ambiguous and the turn ABSTAINS instead of guessing.
                    A follow-up that names no actor and whose rewrite takes
                    the conversation's actor is the purpose of rewriting, not
                    a conflict.
  dual retrieval    (Stage 1b) a served rewrite retrieves on BOTH the raw
                    follow-up and the rewrite; the two RRF candidate lists are
                    fused by summed score, deduplicated by chunk id, before
                    the actor prior and the 15-chunk slice. Generation sees
                    the rewrite, so "that" is resolved; it still answers from
                    the retrieved context only. Stage 1 had replaced the query
                    and lost Article 99(4) to "CE marking" saturating BM25.
  answerability     if the fused retrieval returns no candidate the turn
                    abstains. There is no further retry: a rewrite that finds
                    nothing is not a licence to guess a referent.
  audit             query_trace.rewritten_query holds the served rewrite;
                    retrieval_config carries |rewrite=applied, |rewrite=guarded
                    or |rewrite=ambiguous so every outcome is queryable.

Stage 2 (22 Sep 2026): the grade node, active only when
config.agentic_grade_enabled() (AGENTIC_GRADE, effective inside the graph
only). See app.generation.grade: one gpt-4o-mini relevance grade over the
slice; proceed (relevant passages first, nothing dropped), widen ONCE
in-corpus at a larger breadth and re-grade, or abstain before any gpt-4o
call. No web, no content, no loop. retrieval_config carries |grade=proceed,
|grade=widened, |grade=abstain or |grade=skipped (grader failure, slice served
as retrieved).

Stage 3 (22 Sep 2026): the verify node after generate, active only when
config.agentic_verify_enabled() (AGENTIC_VERIFY, effective inside the graph
only). See app.generation.verify: every provision the answer names must be
in the context (deterministic) and every cited claim must be entailed by its
passage (VERIFY_MODEL). A misgrounded answer is regenerated ONCE with a
grounding instruction and re-verified; still misgrounded, the turn abstains.
retrieval_config carries |verify=passed, |verify=regenerated,
|verify=abstained or |verify=skipped (verifier failure, answer served as
generated). Bounded: one regeneration, no loop; the verifier adds nothing.

Grounding, citations and the refusal sentence are decided downstream by the
unchanged decide step.

The graph carries the SQLAlchemy session and pydantic objects in its state as
plain Python values. There is no checkpointer and nothing is serialised, so
nothing leaves the process. LangSmith tracing is not configured and stays off
unless its own environment variables are set.
"""

from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.config import (
    agentic_grade_enabled,
    agentic_rewrite_enabled,
    agentic_verify_enabled,
)
from app.generation import answer as pipeline
from app.generation.answer import (
    GenerationStep,
    GroundedAnswer,
    RetrievalStep,
    RewriteInfo,
)
from app.generation.grade import (
    WIDEN_BREADTH,
    WIDEN_SLICE,
    GradeResult,
    grade_context,
    reorder,
)
from app.generation.rewrite import RewriteResult, load_history, rewrite_followup
from app.generation.verify import (
    VerifyResult,
    regeneration_instruction,
    verify_answer,
)
from app.retrieval.actor import detect_query_actor

PATH_TAG = "|path=graph"
REWRITE_TAGS = {
    "applied": "|rewrite=applied",
    "guarded": "|rewrite=guarded",
    "ambiguous": "|rewrite=ambiguous",
}
GRADE_TAGS = {
    "proceed": "|grade=proceed",
    "widened": "|grade=widened",
    "abstain": "|grade=abstain",
    "skipped": "|grade=skipped",
}
VERIFY_TAGS = {
    "passed": "|verify=passed",
    "regenerated": "|verify=regenerated",
    "abstained": "|verify=abstained",
    "skipped": "|verify=skipped",
}
AMBIGUOUS_CONFIG = "none|abstain=ambiguous_actor"


class GraphState(TypedDict, total=False):
    # inputs
    session: Any
    query: str
    stored_text: str
    corpus_version_id: int
    chat_session_id: UUID
    final_context_size: int
    min_similarity: float
    write_trace: bool
    max_output_tokens: int | None
    rewrite: RewriteInfo | None
    # produced by nodes
    raw_query: str | None  # the follow-up as typed, when a rewrite was served
    rewrite_result: RewriteResult | None
    rewrite_outcome: str | None  # applied | guarded | ambiguous | None
    retrieved: RetrievalStep
    grade_outcome: str | None  # proceed | widened | abstain | skipped | None
    grade_results: list[GradeResult]
    generated: GenerationStep
    verify_outcome: str | None  # passed | regenerated | abstained | skipped | None
    verify_results: list[VerifyResult]
    result: GroundedAnswer


def actor_conflict(original: str, rewritten: str) -> bool:
    """True when the original follow-up names exactly one actor and the
    rewrite does not name that same one. None on the original means the
    follow-up left the actor to the conversation, which is not a conflict."""
    before = detect_query_actor(original)
    if before is None:
        return False
    return detect_query_actor(rewritten) != before


def rewrite(state: GraphState) -> dict:
    if not agentic_rewrite_enabled():
        return {}
    upstream = state.get("rewrite")
    if upstream is not None and upstream.applied:
        # The route already rewrote this turn (FOLLOWUP_REWRITE); never twice.
        return {}
    history = load_history(state["session"], state["chat_session_id"])
    res = rewrite_followup(history, state["query"])
    info = RewriteInfo(
        applied=res.applied,
        prompt_tokens=res.prompt_tokens,
        completion_tokens=res.completion_tokens,
    )
    if not res.applied:
        outcome = "guarded" if res.introduced else None
        return {"rewrite": info, "rewrite_result": res, "rewrite_outcome": outcome}
    if actor_conflict(res.original, res.query):
        return {
            "rewrite": RewriteInfo(
                applied=False,
                prompt_tokens=res.prompt_tokens,
                completion_tokens=res.completion_tokens,
            ),
            "rewrite_result": res,
            "rewrite_outcome": "ambiguous",
        }
    return {
        "query": res.query,
        "raw_query": res.original,
        "rewrite": info,
        "rewrite_result": res,
        "rewrite_outcome": "applied",
    }


def retrieve(state: GraphState) -> dict:
    # Stage 1b: a served rewrite retrieves on the raw follow-up AND the
    # rewrite, fused (answer.retrieve_candidates_dual). Otherwise Stage 0.
    return {
        "retrieved": pipeline.retrieve_step(
            state["session"],
            state["query"],
            state["corpus_version_id"],
            min_similarity=state["min_similarity"],
            final_context_size=state["final_context_size"],
            raw_query=state.get("raw_query"),
        )
    }


def _graded_step(
    step: RetrievalStep, result: GradeResult, context_size: int
) -> RetrievalStep:
    """The slice with relevant passages first, capped at the normal context
    size; the wider candidate list follows in the trace order."""
    ordered = reorder(step.fused, result.relevant)
    rest = [f for f in step.all_fused if f not in step.fused]
    return RetrievalStep(
        all_fused=[*ordered, *rest],
        fused=ordered[:context_size],
        retrieval_config=step.retrieval_config,
        latency_ms=step.latency_ms,
    )


def grade(state: GraphState) -> dict:
    """proceed / widen once / abstain. Bounded: exactly one possible
    re-retrieval, no loop, no fetch outside the corpus."""
    if not agentic_grade_enabled():
        return {}
    step = state["retrieved"]
    context_size = state["final_context_size"]
    first = grade_context(state["query"], step.fused)
    results = [first]
    if not first.ok:
        return {"grade_outcome": "skipped", "grade_results": results}
    if first.relevant:
        return {
            "retrieved": _graded_step(step, first, context_size),
            "grade_outcome": "proceed",
            "grade_results": results,
        }
    # Nothing relevant in the normal slice: one wider in-corpus pass.
    wider = pipeline.retrieve_step(
        state["session"],
        state["query"],
        state["corpus_version_id"],
        min_similarity=state["min_similarity"],
        final_context_size=WIDEN_SLICE,
        raw_query=state.get("raw_query"),
        breadth=WIDEN_BREADTH,
    )
    wider = RetrievalStep(
        all_fused=wider.all_fused,
        fused=wider.fused,
        retrieval_config=wider.retrieval_config,
        latency_ms=step.latency_ms + wider.latency_ms,
    )
    second = grade_context(state["query"], wider.fused)
    results.append(second)
    if not second.ok:
        # The widen itself is not evidence; serve the original slice as retrieved.
        return {"grade_outcome": "skipped", "grade_results": results}
    if second.relevant:
        return {
            "retrieved": _graded_step(wider, second, context_size),
            "grade_outcome": "widened",
            "grade_results": results,
        }
    empty = RetrievalStep(
        all_fused=wider.all_fused,
        fused=[],
        retrieval_config=wider.retrieval_config,
        latency_ms=wider.latency_ms,
    )
    return {"retrieved": empty, "grade_outcome": "abstain", "grade_results": results}


def generate(state: GraphState) -> dict:
    return {
        "generated": pipeline.generate_step(
            state["query"],
            state["retrieved"].fused,
            max_output_tokens=state["max_output_tokens"],
        )
    }


def _abstain_step(
    first: GenerationStep, second: GenerationStep | None
) -> GenerationStep:
    """An abstention that keeps the spend of every draft on the trace."""
    drafts = [d for d in (first, second) if d is not None]
    return GenerationStep(
        answer_text=pipeline.ABSTENTION_TEXT,
        prompt_tokens=sum(d.prompt_tokens or 0 for d in drafts) or None,
        completion_tokens=sum(d.completion_tokens or 0 for d in drafts) or None,
        latency_ms=sum(d.latency_ms or 0 for d in drafts) or None,
    )


def verify(state: GraphState) -> dict:
    """passed / regenerated once / abstained. Bounded: one regeneration, no
    loop. Only tightens: it can replace an answer with a better-grounded
    draft or with the abstention, never with added content."""
    if not agentic_verify_enabled():
        return {}
    generated = state.get("generated")
    if generated is None or generated.answer_text is None:
        return {}
    if pipeline.is_abstention(generated.answer_text):
        return {}
    fused = state["retrieved"].fused
    first = verify_answer(generated.answer_text, fused)
    results = [first]
    if not first.ok and not first.misgrounded:
        return {"verify_outcome": "skipped", "verify_results": results}
    if not first.misgrounded:
        return {"verify_outcome": "passed", "verify_results": results}
    redo = pipeline.generate_step(
        state["query"],
        fused,
        max_output_tokens=state["max_output_tokens"],
        extra_instruction=regeneration_instruction(first),
    )
    merged = GenerationStep(
        answer_text=redo.answer_text,
        prompt_tokens=(generated.prompt_tokens or 0) + (redo.prompt_tokens or 0),
        completion_tokens=(generated.completion_tokens or 0)
        + (redo.completion_tokens or 0),
        latency_ms=(generated.latency_ms or 0) + (redo.latency_ms or 0),
    )
    if redo.answer_text is None or pipeline.is_abstention(redo.answer_text):
        return {
            "generated": _abstain_step(generated, redo),
            "verify_outcome": "abstained",
            "verify_results": results,
        }
    second = verify_answer(redo.answer_text, fused)
    results.append(second)
    if second.ok and not second.misgrounded:
        return {
            "generated": merged,
            "verify_outcome": "regenerated",
            "verify_results": results,
        }
    if not second.ok and not second.misgrounded:
        # Verifier failed on the second pass: the first draft was rejected on
        # evidence, the second cannot be checked. Abstain rather than serve
        # an unverified draft of an answer already found misgrounded.
        return {
            "generated": _abstain_step(generated, redo),
            "verify_outcome": "abstained",
            "verify_results": results,
        }
    return {
        "generated": _abstain_step(generated, redo),
        "verify_outcome": "abstained",
        "verify_results": results,
    }


def decide(state: GraphState) -> dict:
    retrieved = state.get("retrieved") or RetrievalStep(
        all_fused=[], fused=[], retrieval_config=AMBIGUOUS_CONFIG, latency_ms=0
    )
    generated = state.get("generated") or GenerationStep(None, None, None, None)
    tag = (
        REWRITE_TAGS.get(state.get("rewrite_outcome") or "", "")
        + GRADE_TAGS.get(state.get("grade_outcome") or "", "")
        + VERIFY_TAGS.get(state.get("verify_outcome") or "", "")
        + PATH_TAG
    )
    return {
        "result": pipeline.decide_step(
            state["session"],
            state["query"],
            state["stored_text"],
            state["corpus_version_id"],
            state["chat_session_id"],
            retrieved,
            generated,
            final_context_size=state["final_context_size"],
            write_trace=state["write_trace"],
            rewrite=state.get("rewrite"),
            path_tag=tag,
        )
    }


def route_after_rewrite(state: GraphState) -> str:
    return "decide" if state.get("rewrite_outcome") == "ambiguous" else "retrieve"


def route_after_retrieve(state: GraphState) -> str:
    """No context means the plain path never calls the model; the graph must
    not either. Otherwise the slice goes to the grader (inert when off)."""
    return "grade" if state["retrieved"].fused else "decide"


def route_after_grade(state: GraphState) -> str:
    return "decide" if state.get("grade_outcome") == "abstain" else "generate"


def build_graph() -> StateGraph:
    g = StateGraph(GraphState)
    g.add_node("rewrite", rewrite)
    g.add_node("retrieve", retrieve)
    g.add_node("grade", grade)
    g.add_node("generate", generate)
    g.add_node("verify", verify)
    g.add_node("decide", decide)
    g.add_edge(START, "rewrite")
    g.add_conditional_edges(
        "rewrite", route_after_rewrite, {"retrieve": "retrieve", "decide": "decide"}
    )
    g.add_conditional_edges(
        "retrieve", route_after_retrieve, {"grade": "grade", "decide": "decide"}
    )
    g.add_conditional_edges(
        "grade", route_after_grade, {"generate": "generate", "decide": "decide"}
    )
    g.add_edge("generate", "verify")
    g.add_edge("verify", "decide")
    g.add_edge("decide", END)
    return g


GRAPH = build_graph().compile()


def run_graph(
    *,
    session: Any,
    query: str,
    stored_text: str,
    corpus_version_id: int,
    chat_session_id: UUID,
    final_context_size: int = 15,
    min_similarity: float = 0.3,
    write_trace: bool = True,
    max_output_tokens: int | None = None,
    rewrite: RewriteInfo | None = None,
) -> GroundedAnswer:
    final: GraphState = GRAPH.invoke(
        {
            "session": session,
            "query": query,
            "stored_text": stored_text,
            "corpus_version_id": corpus_version_id,
            "chat_session_id": chat_session_id,
            "final_context_size": final_context_size,
            "min_similarity": min_similarity,
            "write_trace": write_trace,
            "max_output_tokens": max_output_tokens,
            "rewrite": rewrite,
        }
    )
    return final["result"]
