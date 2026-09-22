import sys
import time
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import app_env
from app.db.models import ChatSession, Citation, Message, QueryTrace, RetrievalTrace
from app.ingestion.embedder import _get_client
from app.retrieval.actor import (
    ACTOR_MISMATCH_FACTOR,
    apply_actor_prior,
    detect_query_actor,
)
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

# Dense anchor (22 Sep 2026). RRF at 0.4/0.6 gives a vector-only rank-1 chunk
# 0.4/61 = 0.0066, while any lexical-only chunk inside BM25's top 25 scores at
# least 0.6/85 = 0.0071: when BM25 is saturated with generic matches ("who is
# a provider?" matches "provider" everywhere) the semantically best chunk
# cannot even enter the candidate list. Diagnosed on the broad-question set:
# the Article 3 definitions ranked #1 on the vector leg and were absent from
# the fused 25. The rule below guarantees the top vector hit a place at the
# front of the context when its similarity clears the floor and fusion left
# it out. Floor chosen from the sweep in evals/run_broad_eval.py --golden.
DENSE_ANCHOR_FLOOR = 0.45
DENSE_ANCHOR_POSITION = 5  # 0-indexed: sixth in the context, below the fused top five

ABSTENTION_TEXT = (
    "I don't have enough information in the retrieved EU AI Act provisions "
    "to answer this question."
)


def is_abstention(text: str) -> bool:
    """The model is told to reply with EXACTLY the abstention sentence, and it
    occasionally wraps it in the quotation marks the prompt shows it in. That
    variant is still a refusal; treating it as an answer would attach fifteen
    citations to a sentence that says there are none."""
    t = text.strip().strip("\"'\u201c\u201d\u2018\u2019").strip()
    return t.rstrip(".").lower() == ABSTENTION_TEXT.rstrip(".").lower()


SYSTEM_PROMPT = (
    "You are a legal compliance copilot answering questions about the EU AI Act.\n"
    "Answer using ONLY the context provided below. Do not use any outside knowledge.\n"
    "If the context does not contain enough information to answer the question, "
    f'reply with EXACTLY this sentence and nothing else: "{ABSTENTION_TEXT}"\n'
    # Added 22 Sep 2026 after the broad-question eval: with Article 6(1) at
    # rank 1 the model refused "what is a high-risk AI system?" in most runs,
    # treating a classification rule as "not a definition". The governing
    # provision is the answer to such a question; this names that case
    # without widening the grounding rule (still context only, still abstain
    # when nothing in the context bears on the question).
    "The context often contains the provision that GOVERNS the question rather "
    "than a sentence phrased as a direct answer: a definition in Article 3, a "
    "classification rule such as Article 6 or Annex III, a scope rule, or a list "
    "of obligations or prohibitions. When it does, answer from that provision and "
    "cite it; do not abstain merely because it is phrased as conditions or a rule "
    "rather than as a definition. Abstain only when no provision in the context "
    "bears on the question.\n"
    "When you do answer, reference the relevant provisions by their citation label "
    '(e.g. "Article 6, paragraph 2") inline in your answer.'
)


class GroundedAnswer(BaseModel):
    answer: str
    citations: list[SearchResult]
    message_id: UUID


class RewriteInfo(BaseModel):
    """What a follow-up rewrite (app.generation.rewrite) did, for the trace.
    Defaults describe a first turn: nothing attempted, nothing recorded."""

    applied: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def trace_fields(self, query: str) -> dict:
        return {
            "rewritten_query": query if self.applied else None,
            "rewrite_prompt_tokens": self.prompt_tokens,
            "rewrite_completion_tokens": self.completion_tokens,
        }


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
    rewritten_query: str | None = None,
    rewrite_prompt_tokens: int | None = None,
    rewrite_completion_tokens: int | None = None,
) -> None:
    """Best-effort. Called strictly AFTER _persist_turn has already committed
    the product message/citations, as a fully independent transaction. Any
    failure here is caught, logged, and swallowed - never re-raised - so it
    can never undo or block the user's already-saved answer."""
    try:
        # The user is stored on the trace itself (not only via the session) so
        # the quota and audit rows outlive a deleted chat.
        user_id = session.execute(
            select(ChatSession.user_id).where(ChatSession.id == chat_session_id)
        ).scalar_one()
        trace = QueryTrace(
            user_id=user_id,
            chat_session_id=chat_session_id,
            corpus_version_id=corpus_version_id,
            query_text=query_text,
            answer_text=result.answer,
            abstained=(result.answer == ABSTENTION_TEXT),
            model=CHAT_MODEL,
            environment=app_env(),
            # What actually served this turn - "hybrid_bm25" or
            # "vector_only_degraded" - never a fixed string, so a silent
            # degradation is queryable rather than invisible.
            retrieval_config=retrieval_config,
            retrieval_latency_ms=retrieval_latency_ms,
            generation_latency_ms=generation_latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            # Follow-up rewriting (turn 2+): the standalone query retrieval
            # actually ran on, and what the rewrite cost. NULL on a first
            # turn or when the rewrite was not applied.
            rewritten_query=rewritten_query,
            rewrite_prompt_tokens=rewrite_prompt_tokens,
            rewrite_completion_tokens=rewrite_completion_tokens,
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


def apply_dense_anchor(
    all_fused: list[FusedResult],
    vector_results: list[SearchResult],
    *,
    floor: float = DENSE_ANCHOR_FLOOR,
    context_size: int = 15,
    position: int = DENSE_ANCHOR_POSITION,
) -> tuple[list[FusedResult], bool]:
    """If the top vector hit clears `floor` and is not already inside the
    context slice, insert it at `position` (0-indexed). Returns (fused,
    anchored). Pure. Position 5 keeps the fused top five exactly as they
    were, so recall@5 on the golden sets is unchanged by construction; the
    anchored chunk still sits well inside the 15-chunk context."""
    if not vector_results or floor is None:
        return all_fused, False
    top = vector_results[0]
    if top.similarity < floor:
        return all_fused, False
    if any(f.result.chunk_id == top.chunk_id for f in all_fused[:context_size]):
        return all_fused, False
    rest = [f for f in all_fused if f.result.chunk_id != top.chunk_id]
    anchored = FusedResult(result=top, rrf_score=0.0, vector_rank=0, lexical_rank=None)
    at = min(position, len(rest))
    merged = [*rest[:at], anchored, *rest[at:]]
    return merged[: max(len(all_fused), 1)], True


def retrieve_candidates(
    session: Session,
    query: str,
    corpus_version_id: int,
    *,
    min_similarity: float = 0.3,
    dense_anchor_floor: float | None | str = "default",
    final_context_size: int = 15,
) -> tuple[list[FusedResult], str]:
    """The production candidate list: vector + BM25, RRF, actor prior, dense
    anchor. One function so the evals measure exactly what /ask serves.
    Returns (fused candidates, retrieval_config string)."""
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
    # Advisory actor prior, applied over the FULL candidate list before the
    # slice: when the question names exactly one actor, chunks labelled with
    # a different actor sink. Recorded in retrieval_config either way, so a
    # trace row always says whether the prior fired ("actor=none" means it
    # ran and declined, not that it was absent).
    query_actor = detect_query_actor(query)
    all_fused = apply_actor_prior(all_fused, query_actor, ACTOR_MISMATCH_FACTOR)
    retrieval_config += f"|actor={query_actor or 'none'}"
    if query_actor is not None:
        retrieval_config += f"|factor={ACTOR_MISMATCH_FACTOR}"
    # "default" resolves at call time, so an eval can sweep the module
    # constant and the generation path follows it.
    floor = (
        DENSE_ANCHOR_FLOOR if dense_anchor_floor == "default" else dense_anchor_floor
    )
    if floor is not None:
        all_fused, anchored = apply_dense_anchor(
            all_fused,
            vector_results,
            floor=floor,
            context_size=final_context_size,
        )
        if anchored:
            retrieval_config += "|anchor=dense"
    return all_fused, retrieval_config


def generate_grounded_answer(
    session: Session,
    query: str,
    corpus_version_id: int,
    chat_session_id: UUID,
    final_context_size: int = 15,
    min_similarity: float = 0.3,
    write_trace: bool = True,
    max_output_tokens: int | None = None,
    user_text: str | None = None,
    rewrite: "RewriteInfo | None" = None,
) -> GroundedAnswer:
    """max_output_tokens bounds the expensive half of a call (gpt-4o output is
    4x input cost). Default None preserves the previous unbounded behaviour
    exactly, so existing callers and eval runs are unaffected; the HTTP
    surface passes an explicit ceiling.

    `query` is what retrieval and the prompt see. `user_text`, when given, is
    what the user actually typed and is what gets persisted as their message
    and as query_text on the trace; a follow-up rewrite (app.generation.rewrite)
    passes the standalone question as `query` and the original as `user_text`.
    Everything from retrieval onwards is identical either way."""
    stored_text = user_text if user_text is not None else query
    rw = rewrite or RewriteInfo()
    retrieval_start = time.monotonic()
    all_fused, retrieval_config = retrieve_candidates(
        session, query, corpus_version_id, min_similarity=min_similarity
    )
    retrieval_latency_ms = int((time.monotonic() - retrieval_start) * 1000)

    # Equivalent to the old rrf_rank_and_fuse(..., top_k=final_context_size):
    # rrf_rank_and_fuse sorts the full candidate set by rrf_score BEFORE
    # trimming to top_k, and rrf_score doesn't depend on top_k at all - so
    # widening to RETRIEVAL_CANDIDATE_BREADTH and slicing locally yields the
    # identical top final_context_size, in the same order, every time. The
    # actor prior re-sorts that same full list, so the slice still takes the
    # true top final_context_size of the final ordering.
    fused = all_fused[:final_context_size]

    if not fused:
        message = _persist_turn(
            session, chat_session_id, stored_text, ABSTENTION_TEXT, fused=[]
        )
        result = GroundedAnswer(
            answer=ABSTENTION_TEXT, citations=[], message_id=message.id
        )
        if write_trace:
            _write_trace_safe(
                session,
                chat_session_id,
                stored_text,
                result,
                corpus_version_id,
                retrieval_latency_ms,
                generation_latency_ms=None,
                prompt_tokens=None,
                completion_tokens=None,
                all_fused=all_fused,
                final_context_size=final_context_size,
                retrieval_config=retrieval_config,
                **rw.trace_fields(query),
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

    if is_abstention(answer_text):
        # The LLM itself decided the retrieved context didn't actually answer
        # the question. Persist the same shape as the pre-LLM abstention -
        # refusal text, zero citations - not citations for chunks the model
        # just told us were insufficient.
        message = _persist_turn(
            session, chat_session_id, stored_text, ABSTENTION_TEXT, fused=[]
        )
        result = GroundedAnswer(
            answer=ABSTENTION_TEXT, citations=[], message_id=message.id
        )
    else:
        message = _persist_turn(
            session, chat_session_id, stored_text, answer_text, fused=fused
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
            stored_text,
            result,
            corpus_version_id,
            retrieval_latency_ms,
            generation_latency_ms,
            prompt_tokens,
            completion_tokens,
            all_fused=all_fused,
            final_context_size=final_context_size,
            retrieval_config=retrieval_config,
            **rw.trace_fields(query),
        )
    return result
