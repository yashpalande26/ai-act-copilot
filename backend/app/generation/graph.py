"""Stage 0 of the agentic-RAG plan: the grounded-answer pipeline as a
LangGraph graph, behind AGENTIC_RAG=1 (default off).

    START -> retrieve -> generate -> decide -> END
    (retrieve -> decide directly when there is no context: the model is not
    called and decide abstains, exactly as the plain path does)

Every node calls the step function of the same name in app.generation.answer
and nothing else, so the graph is a different EXECUTION of the same code, not
a second implementation. No node is agentic yet: no rewriting, no grading, no
verification, no decomposition. Later stages add nodes here, each behind its
own flag and gated against the plain path with evals/gate.py.

The graph carries the SQLAlchemy session and pydantic objects in its state as
plain Python values. There is no checkpointer and nothing is serialised, so
nothing leaves the process. LangSmith tracing is not configured and stays off
unless its own environment variables are set.
"""

from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.generation import answer as pipeline
from app.generation.answer import (
    GenerationStep,
    GroundedAnswer,
    RetrievalStep,
    RewriteInfo,
)

PATH_TAG = "|path=graph"


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
    retrieved: RetrievalStep
    generated: GenerationStep
    result: GroundedAnswer


def retrieve(state: GraphState) -> dict:
    return {
        "retrieved": pipeline.retrieve_step(
            state["session"],
            state["query"],
            state["corpus_version_id"],
            min_similarity=state["min_similarity"],
            final_context_size=state["final_context_size"],
        )
    }


def generate(state: GraphState) -> dict:
    return {
        "generated": pipeline.generate_step(
            state["query"],
            state["retrieved"].fused,
            max_output_tokens=state["max_output_tokens"],
        )
    }


def decide(state: GraphState) -> dict:
    generated = state.get("generated") or GenerationStep(None, None, None, None)
    return {
        "result": pipeline.decide_step(
            state["session"],
            state["query"],
            state["stored_text"],
            state["corpus_version_id"],
            state["chat_session_id"],
            state["retrieved"],
            generated,
            final_context_size=state["final_context_size"],
            write_trace=state["write_trace"],
            rewrite=state["rewrite"],
            path_tag=PATH_TAG,
        )
    }


def route_after_retrieve(state: GraphState) -> str:
    """No context means the plain path never calls the model; the graph must
    not either. This is the edge a Stage 2 retrieval grader would sit on."""
    return "generate" if state["retrieved"].fused else "decide"


def build_graph() -> StateGraph:
    g = StateGraph(GraphState)
    g.add_node("retrieve", retrieve)
    g.add_node("generate", generate)
    g.add_node("decide", decide)
    g.add_edge(START, "retrieve")
    g.add_conditional_edges(
        "retrieve", route_after_retrieve, {"generate": "generate", "decide": "decide"}
    )
    g.add_edge("generate", "decide")
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
