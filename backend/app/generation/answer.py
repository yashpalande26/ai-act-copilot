import sys
import time
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Citation, Message, QueryTrace, RetrievalTrace
from app.ingestion.embedder import _get_client
from app.retrieval.bm25_index import StaleIndexError, load_index
from app.retrieval.search import (
    FusedResult,
    SearchResult,
    bm25_search,
    rrf_rank_and_fuse,
    vector_search,
)

CHAT_MODEL = "gpt-4o"

# RRF fusion weights for the production retriever, paired with a BM25 leg over
# index_text (see bm25_index.fetch_indexable_chunks). Measured on three eval
# sets, 0.6 beat 0.5 on ALL of them independently - realistic MRR 0.939 vs
# 0.914, hard 0.902 vs 0.826, easy 0.885 vs 0.865 - which is stronger evidence
# than a peak on any single set. Honest cost: the easy set still prefers
# vector-only by 0.011 MRR (0.896 vs 0.885), roughly one question slipping one
# rank out of 16, and inside this corpus's noise floor.
# Passed explicitly rather than changed in rrf_rank_and_fuse's defaults, which
# still back run_eval's historical "hybrid" FTS reference config.
RETRIEVAL_VECTOR_WEIGHT = 0.4
RETRIEVAL_LEXICAL_WEIGHT = 0.6

# Candidate breadth for vector/lexical retrieval AND for rrf_rank_and_fuse's
# own top_k - kept wide so used_in_context on RetrievalTrace rows is
# meaningful (there are candidates that didn't make the final cut to trace
# against). The actual prompt/citations still only use the top
# final_context_size of this - see the equivalence note in generate_grounded_answer.
RETRIEVAL_CANDIDATE_BREADTH = 25

ABSTENTION_TEXT = (
    "I don't have enough information in the retrieved EU AI Act provisions "
    "to answer this question."
)

SYSTEM_PROMPT = (
    "You are a legal compliance copilot answering questions about the EU AI Act.\n"
    "Answer using ONLY the context provided below. Do not use any outside knowledge.\n"
    "If the context does not contain enough information to answer the question, "
    f'reply with EXACTLY this sentence and nothing else: "{ABSTENTION_TEXT}"\n'
    "When you do answer, reference the relevant provisions by their citation label "
    '(e.g. "Article 6, paragraph 2") inline in your answer.'
)


class GroundedAnswer(BaseModel):
    answer: str
    citations: list[SearchResult]
    message_id: UUID


def _lexical_leg(
    session: Session, query: str, corpus_version_id: int
) -> tuple[list[SearchResult], str]:
    """BM25 retrieval with a safe fallback. Returns (results, retrieval_config).

    Two hard rules meet here. We must never serve WRONG citations: a stale
    index resolves its doc->chunk_id mapping against the wrong rows, so it can
    never be used. And we must never take the whole copilot down over
    retrieval infrastructure: vector-only results are always correct, so
    degrading to them satisfies that without violating the first rule.

    The returned config string is what actually ran, not what we intended to
    run - so query_trace can answer "how long have we been degraded?".
    """
    try:
        # Checked explicitly rather than inferred from an empty result: BM25
        # can legitimately return [] for a query whose terms are all stopwords
        # while the index is perfectly healthy, and that is NOT degradation.
        if load_index(corpus_version_id) is None:
            # Logged on every request, deliberately: a missing index means the
            # deploy step never ran and EVERY turn is silently degraded. Noisy
            # is the right failure mode for a misconfiguration that costs
            # retrieval quality on all traffic.
            print(
                "ACTION REQUIRED: no bm25 index for corpus_version "
                f"{corpus_version_id}, serving vector-only. Build it with "
                "scripts/build_bm25_index.py.",
                file=sys.stderr,
            )
            return [], "vector_only_degraded"
        results = bm25_search(
            session, query, corpus_version_id, top_k=RETRIEVAL_CANDIDATE_BREADTH
        )
        return results, "hybrid_bm25"
    except StaleIndexError as exc:
        print(
            "ACTION REQUIRED: bm25 index is stale, serving vector-only. "
            f"Rebuild with scripts/build_bm25_index.py. {exc}",
            file=sys.stderr,
        )
        return [], "vector_only_degraded"
    except Exception as exc:  # noqa: BLE001 - uptime beats a hard failure when a correct fallback exists; the distinct banner keeps real bugs visible
        print(
            f"UNEXPECTED bm25 failure, serving vector-only: {exc!r}",
            file=sys.stderr,
        )
        return [], "vector_only_degraded"


def _build_user_prompt(query: str, fused: list[FusedResult]) -> str:
    blocks = []
    for f in fused:
        r = f.result
        heading = f" — {r.article_heading}" if r.article_heading else ""
        blocks.append(f"[{r.citation_label}{heading}]\n{r.chunk_text}")
    context_block = "\n\n".join(blocks)
    return f"Context:\n{context_block}\n\nQuestion: {query}"


def _persist_turn(
    session: Session,
    chat_session_id: UUID,
    query_text: str,
    answer_text: str,
    fused: list[FusedResult],
) -> Message:
    try:
        session.add(
            Message(session_id=chat_session_id, role="user", content=query_text)
        )
        assistant_message = Message(
            session_id=chat_session_id, role="assistant", content=answer_text
        )
        session.add(assistant_message)
        session.flush()  # assigns both messages' ids

        for f in fused:
            session.add(
                Citation(
                    message_id=assistant_message.id,
                    chunk_id=f.result.chunk_id,
                    provision_citation_id=f.result.citation_id,
                    quoted_text=f.result.chunk_text,
                )
            )
        session.commit()
        return assistant_message
    except Exception:
        session.rollback()
        raise


def _write_trace_safe(
    session: Session,
    chat_session_id: UUID,
    query_text: str,
    result: GroundedAnswer,
    corpus_version_id: int,
    retrieval_latency_ms: int,
    generation_latency_ms: int | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    all_fused: list[FusedResult],
    final_context_size: int,
    retrieval_config: str,
) -> None:
    """Best-effort. Called strictly AFTER _persist_turn has already committed
    the product message/citations, as a fully independent transaction. Any
    failure here is caught, logged, and swallowed - never re-raised - so it
    can never undo or block the user's already-saved answer."""
    try:
        trace = QueryTrace(
            chat_session_id=chat_session_id,
            corpus_version_id=corpus_version_id,
            query_text=query_text,
            answer_text=result.answer,
            abstained=(result.answer == ABSTENTION_TEXT),
            model=CHAT_MODEL,
            # What actually served this turn - "hybrid_bm25" or
            # "vector_only_degraded" - never a fixed string, so a silent
            # degradation is queryable rather than invisible.
            retrieval_config=retrieval_config,
            retrieval_latency_ms=retrieval_latency_ms,
            generation_latency_ms=generation_latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        session.add(trace)
        session.flush()

        for rank, f in enumerate(all_fused, start=1):
            session.add(
                RetrievalTrace(
                    query_trace_id=trace.id,
                    chunk_id=f.result.chunk_id,
                    provision_citation_id=f.result.citation_id,
                    final_rank=rank,
                    rrf_score=f.rrf_score,
                    vector_rank=f.vector_rank,
                    lexical_rank=f.lexical_rank,
                    similarity=f.result.similarity,
                    used_in_context=rank <= final_context_size,
                )
            )
        session.commit()
    except Exception as exc:  # noqa: BLE001 - best-effort by design: any failure mode must be swallowed, not just anticipated ones
        session.rollback()
        print(
            f"query_trace write failed (best-effort, ignored): {exc}", file=sys.stderr
        )


def generate_grounded_answer(
    session: Session,
    query: str,
    corpus_version_id: int,
    chat_session_id: UUID,
    final_context_size: int = 15,
    min_similarity: float = 0.3,
    write_trace: bool = True,
    max_output_tokens: int | None = None,
) -> GroundedAnswer:
    """max_output_tokens bounds the expensive half of a call (gpt-4o output is
    4x input cost). Default None preserves the previous unbounded behaviour
    exactly, so existing callers and eval runs are unaffected; the HTTP
    surface passes an explicit ceiling."""
    retrieval_start = time.monotonic()
    vector_results = vector_search(
        session,
        query,
        corpus_version_id,
        top_k=RETRIEVAL_CANDIDATE_BREADTH,
        min_similarity=min_similarity,
    )
    lexical_results, retrieval_config = _lexical_leg(session, query, corpus_version_id)
    # With an empty lexical list every candidate scores
    # RETRIEVAL_VECTOR_WEIGHT * 1/(k + rank + 1), a strictly decreasing
    # function of the vector rank - so a degraded turn reproduces
    # vector_search's ordering exactly, not merely approximately.
    all_fused = rrf_rank_and_fuse(
        vector_results,
        lexical_results,
        vector_weight=RETRIEVAL_VECTOR_WEIGHT,
        lexical_weight=RETRIEVAL_LEXICAL_WEIGHT,
        top_k=RETRIEVAL_CANDIDATE_BREADTH,
    )
    retrieval_latency_ms = int((time.monotonic() - retrieval_start) * 1000)

    # Equivalent to the old rrf_rank_and_fuse(..., top_k=final_context_size):
    # rrf_rank_and_fuse sorts the full candidate set by rrf_score BEFORE
    # trimming to top_k, and rrf_score doesn't depend on top_k at all - so
    # widening to RETRIEVAL_CANDIDATE_BREADTH and slicing locally yields the
    # identical top final_context_size, in the same order, every time.
    fused = all_fused[:final_context_size]

    if not fused:
        message = _persist_turn(
            session, chat_session_id, query, ABSTENTION_TEXT, fused=[]
        )
        result = GroundedAnswer(
            answer=ABSTENTION_TEXT, citations=[], message_id=message.id
        )
        if write_trace:
            _write_trace_safe(
                session,
                chat_session_id,
                query,
                result,
                corpus_version_id,
                retrieval_latency_ms,
                generation_latency_ms=None,
                prompt_tokens=None,
                completion_tokens=None,
                all_fused=all_fused,
                final_context_size=final_context_size,
                retrieval_config=retrieval_config,
            )
        return result

    prompt = _build_user_prompt(query, fused)
    generation_start = time.monotonic()
    # Omit max_tokens entirely when unset rather than passing None, so the
    # request body is byte-identical to before for existing callers.
    optional_kwargs = (
        {"max_tokens": max_output_tokens} if max_output_tokens is not None else {}
    )
    response = _get_client().chat.completions.create(
        model=CHAT_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            # The question is a SEPARATE user message; distinct API roles mean
            # user text cannot structurally replace or edit SYSTEM_PROMPT.
            {"role": "user", "content": prompt},
        ],
        **optional_kwargs,
    )
    generation_latency_ms = int((time.monotonic() - generation_start) * 1000)
    answer_text = response.choices[0].message.content
    prompt_tokens = response.usage.prompt_tokens
    completion_tokens = response.usage.completion_tokens

    if answer_text.strip() == ABSTENTION_TEXT:
        # The LLM itself decided the retrieved context didn't actually answer
        # the question. Persist the same shape as the pre-LLM abstention -
        # refusal text, zero citations - not citations for chunks the model
        # just told us were insufficient.
        message = _persist_turn(
            session, chat_session_id, query, ABSTENTION_TEXT, fused=[]
        )
        result = GroundedAnswer(
            answer=ABSTENTION_TEXT, citations=[], message_id=message.id
        )
    else:
        message = _persist_turn(
            session, chat_session_id, query, answer_text, fused=fused
        )
        result = GroundedAnswer(
            answer=answer_text,
            citations=[f.result for f in fused],
            message_id=message.id,
        )

    if write_trace:
        _write_trace_safe(
            session,
            chat_session_id,
            query,
            result,
            corpus_version_id,
            retrieval_latency_ms,
            generation_latency_ms,
            prompt_tokens,
            completion_tokens,
            all_fused=all_fused,
            final_context_size=final_context_size,
            retrieval_config=retrieval_config,
        )
    return result
