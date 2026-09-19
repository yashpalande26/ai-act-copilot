import sys
import time
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Citation, Message, QueryTrace, RetrievalTrace
from app.ingestion.embedder import _get_client
from app.retrieval.search import (
    FusedResult,
    SearchResult,
    keyword_search,
    rrf_rank_and_fuse,
    vector_search,
)

CHAT_MODEL = "gpt-4o"

# Candidate breadth for vector/lexical retrieval AND for rrf_rank_and_fuse's
# own top_k - kept wide so used_in_context on RetrievalTrace rows is
# meaningful (there are candidates that didn't make the final cut to trace
# against). The actual prompt/citations still only use the top
# final_context_size of this - see the equivalence note in generate_grounded_answer.
RETRIEVAL_CANDIDATE_BREADTH = 10

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
            retrieval_config="hybrid",
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
    final_context_size: int = 5,
    min_similarity: float = 0.3,
    write_trace: bool = True,
) -> GroundedAnswer:
    retrieval_start = time.monotonic()
    vector_results = vector_search(
        session,
        query,
        corpus_version_id,
        top_k=RETRIEVAL_CANDIDATE_BREADTH,
        min_similarity=min_similarity,
    )
    lexical_results = keyword_search(
        session, query, corpus_version_id, top_k=RETRIEVAL_CANDIDATE_BREADTH
    )
    all_fused = rrf_rank_and_fuse(
        vector_results, lexical_results, top_k=RETRIEVAL_CANDIDATE_BREADTH
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
            )
        return result

    prompt = _build_user_prompt(query, fused)
    generation_start = time.monotonic()
    response = _get_client().chat.completions.create(
        model=CHAT_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
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
        )
    return result
