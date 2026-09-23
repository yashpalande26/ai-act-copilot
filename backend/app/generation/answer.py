import sys
import time
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import agentic_rag_enabled, app_env, xref_expansion_enabled
from app.db.models import ChatSession, Citation, Message, QueryTrace, RetrievalTrace
from app.generation.provider import (
    PROVIDER_ERRORS,
    ProviderUnavailable,
    describe,
    log_provider_error,
)
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
    fetch_provision_chunks,
    rrf_rank_and_fuse,
    vector_search,
)
from app.retrieval.xref import (
    MAX_XREF_CHUNKS,
    XREF_POINTER_CHUNKS,
    XREF_POSITION,
    apply_xref_expansion,
    resolve_references,
    select_chunks,
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
    '(e.g. "Article 6, paragraph 2") inline in your answer.\n'
    # ADR-32 (23 Sep 2026): recitals are in the context, labelled as such.
    "Passages labelled Recital N (explanatory, non-binding) explain the reasons "
    "behind a rule and are not the rule. Never state a recital as the requirement, "
    "prohibition or classification; the rule comes from an Article or an Annex. "
    "When a recital explains why a rule exists, you may cite it alongside the "
    "Article or Annex point that contains the rule, never on its own."
)


class GroundedAnswer(BaseModel):
    answer: str
    citations: list[SearchResult]
    message_id: UUID
    # The standalone question retrieval actually ran on when a follow-up was
    # rewritten inside the pipeline (Stage 1 graph node); None otherwise. The
    # same value is stored as query_trace.rewritten_query.
    rewritten_query: str | None = None
    # ADR-21: the question described the user's own AI system in plain
    # language; the answer is in explain-and-route mode and the UI shows the
    # route to the assessment. Never a verdict.
    system_description: bool = False
    # Intent gate: a deterministic social-lane reply (greeting, name, thanks,
    # capability). No citations, no legal content.
    social: bool = False
    # Clarifying follow-up: the answer is the copilot's one clarifying
    # question about the described system, not an answer about the Act.
    clarifying: bool = False


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
    session: Session,
    query: str,
    corpus_version_id: int,
    breadth: int = RETRIEVAL_CANDIDATE_BREADTH,
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
        results = bm25_search(session, query, corpus_version_id, top_k=breadth)
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


def _context_blocks(fused: list[FusedResult]) -> str:
    blocks = []
    for f in fused:
        r = f.result
        heading = f" — {r.article_heading}" if r.article_heading else ""
        blocks.append(f"[{r.citation_label}{heading}]\n{r.chunk_text}")
    return "\n\n".join(blocks)


def _build_user_prompt(
    query: str, fused: list[FusedResult], framed_question: str | None = None
) -> str:
    if framed_question:
        # ADR-21: the user's words are shown, but the question the model is
        # asked is the one the chat may answer (what the Act says about this
        # kind of system), not the one it may not (the user's own verdict).
        return (
            f"Context:\n{_context_blocks(fused)}\n\nThe user wrote: {query}\n\n"
            f"Question: {framed_question}"
        )
    return f"Context:\n{_context_blocks(fused)}\n\nQuestion: {query}"


def _build_parts_prompt(query: str, parts: list[tuple[str, list[FusedResult]]]) -> str:
    """Stage 4: one context per sub-question, so each part of the answer is
    grounded in its own passages; the question itself is asked once, whole.
    The grounding rule is the system prompt's, unchanged."""
    sections = [
        f"Context for part {i} ({sub_query}):\n{_context_blocks(fused)}"
        for i, (sub_query, fused) in enumerate(parts, start=1)
    ]
    return (
        "\n\n".join(sections)
        + "\n\nAnswer every part of the question below from the context given "
        "for that part, citing the provisions you rely on. If the context for "
        "a part does not answer it, say so for that part instead of guessing.\n\n"
        f"Question: {query}"
    )


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


def _hybrid_candidates(
    session: Session,
    query: str,
    corpus_version_id: int,
    *,
    min_similarity: float,
    breadth: int = RETRIEVAL_CANDIDATE_BREADTH,
) -> tuple[list[FusedResult], list[SearchResult], str]:
    """The two legs and their RRF fusion for ONE query, before the actor prior
    and the dense anchor. Returns (fused, vector_results, retrieval_config).
    `breadth` is the per-leg depth and the fused list length; only the Stage 2
    grader's single bounded widen passes anything but the default.

    The vector leg is NOT floored in hybrid mode (22 Sep 2026). RRF fuses by
    rank, so a low absolute cosine similarity costs nothing; the old
    `min_similarity` floor silently emptied the whole leg for lay phrasing
    ("property valuation model for bridge lending": every row between 0.20 and
    0.25, Annex III point 5(b) at vector rank 2, none fused) while the label
    still read hybrid_bm25. The floor is applied only when the lexical leg is
    degraded, where it is the pre-LLM abstention gate it always was. A vector
    leg that fails (embedding or pgvector) is degraded to BM25-only under its
    own label and a loud log, mirroring the lexical fallback; a vector leg that
    returns nothing is tagged, so the trace never shows an empty column
    without saying why."""
    vector_error: BaseException | None = None
    try:
        vector_results = vector_search(
            session, query, corpus_version_id, top_k=breadth, min_similarity=0.0
        )
        vector_failed = False
    except Exception as exc:  # noqa: BLE001 - uptime beats a hard failure when a correct fallback exists; the distinct banner keeps real bugs visible
        print(
            f"UNEXPECTED vector leg failure ({describe(exc)}), serving bm25-only",
            file=sys.stderr,
        )
        vector_results, vector_failed, vector_error = [], True, exc
    lexical_results, retrieval_config = _lexical_leg(
        session, query, corpus_version_id, breadth=breadth
    )
    if vector_failed and not lexical_results:
        # No leg can serve: the vector leg failed and BM25 has nothing
        # (degraded index or no match). Not an abstention, an outage.
        log_provider_error("retrieval", vector_error)  # type: ignore[arg-type]
        raise ProviderUnavailable("retrieval", vector_error) from None
    if vector_failed:
        retrieval_config = "bm25_only_degraded"
    elif retrieval_config == "vector_only_degraded":
        # No lexical leg: the floor is the only gate against answering from
        # nothing, exactly as before the hybrid retriever existed.
        vector_results = [r for r in vector_results if r.similarity >= min_similarity]
    if not vector_results and not vector_failed:
        retrieval_config += "|vector=empty"
    # With an empty lexical list every candidate scores
    # RETRIEVAL_VECTOR_WEIGHT * 1/(k + rank + 1), a strictly decreasing
    # function of the vector rank - so a degraded turn reproduces
    # vector_search's ordering exactly, not merely approximately.
    all_fused = rrf_rank_and_fuse(
        vector_results,
        lexical_results,
        vector_weight=RETRIEVAL_VECTOR_WEIGHT,
        lexical_weight=RETRIEVAL_LEXICAL_WEIGHT,
        top_k=breadth,
    )
    return all_fused, vector_results, retrieval_config


def _rank_candidates(
    all_fused: list[FusedResult],
    vector_results: list[SearchResult],
    retrieval_config: str,
    query: str,
    *,
    dense_anchor_floor: float | None | str,
    final_context_size: int,
    session: Session | None = None,
    corpus_version_id: int | None = None,
) -> tuple[list[FusedResult], str]:
    """Actor prior, dense anchor, then cross-reference expansion, on an
    already-fused candidate list. `query` is the question the actor is
    detected on and the references are read from; `session` is needed only
    by the expansion (chunks of the resolved provisions)."""
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
    # Cross-reference expansion (app.retrieval.xref): the provisions the
    # question or the top passages point at, one hop, capped, after the
    # fused top five and the anchor slot. Only fires when a reference is
    # present, so a question without one is untouched by construction.
    if xref_expansion_enabled() and session is not None:
        res = resolve_references(query, [f.result for f in all_fused])
        if res.from_query:
            targets, cap, position, tag = (
                list(res.from_query),
                MAX_XREF_CHUNKS,
                XREF_POSITION,
                "xref",
            )
        else:
            targets, cap, position, tag = (
                list(res.from_pointers),
                XREF_POINTER_CHUNKS,
                max(0, final_context_size - XREF_POINTER_CHUNKS),
                "xref=ptr:",
            )
        if targets:
            by_root = fetch_provision_chunks(session, corpus_version_id, targets)
            present = {f.result.chunk_id for f in all_fused}
            extra = select_chunks(by_root, present, cap=cap)
            all_fused, added = apply_xref_expansion(all_fused, extra, position=position)
            if added:
                retrieval_config += f"|{tag}{'=' if tag == 'xref' else ''}{added}"
    return all_fused, retrieval_config


def retrieve_candidates(
    session: Session,
    query: str,
    corpus_version_id: int,
    *,
    min_similarity: float = 0.3,
    dense_anchor_floor: float | None | str = "default",
    final_context_size: int = 15,
    breadth: int = RETRIEVAL_CANDIDATE_BREADTH,
) -> tuple[list[FusedResult], str]:
    """The production candidate list: vector + BM25, RRF, actor prior, dense
    anchor. One function so the evals measure exactly what /ask serves.
    Returns (fused candidates, retrieval_config string)."""
    all_fused, vector_results, retrieval_config = _hybrid_candidates(
        session,
        query,
        corpus_version_id,
        min_similarity=min_similarity,
        breadth=breadth,
    )
    return _rank_candidates(
        all_fused,
        vector_results,
        retrieval_config,
        query,
        dense_anchor_floor=dense_anchor_floor,
        final_context_size=final_context_size,
        session=session,
        corpus_version_id=corpus_version_id,
    )


def fuse_query_candidates(
    first: list[FusedResult], second: list[FusedResult], *, top_k: int
) -> list[FusedResult]:
    """Fuse the RRF candidate lists of two queries for the same turn. RRF is a
    sum of per-list terms, so adding the two per-query scores of a chunk is
    exactly weighted RRF over the four underlying lists (vector and lexical
    for each query); a chunk both queries retrieve is rewarded, a chunk only
    one retrieves keeps its own score. Deduplicated by chunk id. The trace
    keeps the better vector and lexical rank across the two queries."""
    by_id: dict[int, FusedResult] = {}
    for f in [*first, *second]:
        cur = by_id.get(f.result.chunk_id)
        if cur is None:
            by_id[f.result.chunk_id] = f.model_copy()
            continue
        cur.rrf_score += f.rrf_score
        for attr in ("vector_rank", "lexical_rank"):
            a, b = getattr(cur, attr), getattr(f, attr)
            setattr(
                cur,
                attr,
                min(x for x in (a, b) if x is not None)
                if a is not None or b is not None
                else None,
            )
    fused = sorted(by_id.values(), key=lambda f: f.rrf_score, reverse=True)
    return fused[:top_k]


def retrieve_candidates_dual(
    session: Session,
    raw_query: str,
    rewritten_query: str,
    corpus_version_id: int,
    *,
    min_similarity: float = 0.3,
    dense_anchor_floor: float | None | str = "default",
    final_context_size: int = 15,
    breadth: int = RETRIEVAL_CANDIDATE_BREADTH,
) -> tuple[list[FusedResult], str]:
    """Stage 1b (22 Sep 2026): a rewritten follow-up retrieves on BOTH the
    user's raw follow-up and the standalone rewrite. Each query runs the
    production legs and RRF; the two candidate lists are fused by summed RRF
    (fuse_query_candidates) BEFORE the actor prior and the context slice. The
    raw follow-up keeps the lexical signal the rewrite can lose (measured:
    "penalties for not doing that?" had Article 99(4) at fused rank 2 while
    the rewrite, saturated by "CE marking", dropped it from the 25); the
    rewrite resolves the referent. The actor prior fires on the rewrite (the
    resolved question; the graph has already checked it does not contradict
    the raw one). The dense anchor uses whichever query's top vector hit is
    the more similar. retrieval_config carries |dual."""
    raw_fused, raw_vec, raw_cfg = _hybrid_candidates(
        session,
        raw_query,
        corpus_version_id,
        min_similarity=min_similarity,
        breadth=breadth,
    )
    rw_fused, rw_vec, rw_cfg = _hybrid_candidates(
        session,
        rewritten_query,
        corpus_version_id,
        min_similarity=min_similarity,
        breadth=breadth,
    )
    all_fused = fuse_query_candidates(raw_fused, rw_fused, top_k=breadth)
    # A degraded leg on either query is a degraded turn.
    config = raw_cfg if raw_cfg == rw_cfg else "vector_only_degraded"
    best_vec = max(
        (v for v in (raw_vec, rw_vec) if v), key=lambda v: v[0].similarity, default=[]
    )
    return _rank_candidates(
        all_fused,
        best_vec,
        config + "|dual",
        rewritten_query,
        dense_anchor_floor=dense_anchor_floor,
        final_context_size=final_context_size,
        session=session,
        corpus_version_id=corpus_version_id,
    )


@dataclass
class RetrievalStep:
    """What retrieval produced for one turn. `fused` is the context slice the
    generator sees; `all_fused` is the wider candidate list the trace records."""

    all_fused: list[FusedResult]
    fused: list[FusedResult]
    retrieval_config: str
    latency_ms: int


@dataclass
class GenerationStep:
    """What the model said, or nothing when generation was skipped because
    retrieval returned no context (answer_text None)."""

    answer_text: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None


# The pipeline is three steps. generate_grounded_answer runs them in sequence
# (the plain path); app.generation.graph runs the same three functions as
# LangGraph nodes when AGENTIC_RAG=1. Both paths must call these and nothing
# else, so that "flag on" and "flag off" cannot drift apart.


# Recital demotion (ADR-32, 23 Sep 2026). Recitals are long and semantically
# rich, so once in the corpus they crowd the dense leg: measured on 12
# single-hop items, 4.2 recitals per 15-slice, five items with a recital at
# rank 0, gold mean rank 2.34. The rule below keeps the first RECITAL_MIN_RANK
# positions for operative provisions and admits at most RECITAL_CAP recitals
# into the slice, in fused order; displaced recitals move behind the slice.
# Swept offline on the retrieved lists (cap, head): (4,3) 3.14 recitals and
# gold rank 2.10; (3,5) 2.66 and 1.79; (2,5) 2.10 and 1.72 with all four
# "why" items keeping their gold recital at rank 5 or 6; (1,5) 1.34 but one
# "why" item loses its recital. (2,5) chosen; the head of five matches the
# dense-anchor and xref slots. Yash may move it (ADR-7 rule).
RECITAL_CAP = 2
RECITAL_MIN_RANK = 5


def is_recital_result(f: FusedResult) -> bool:
    return f.result.citation_id.startswith("rec_")


def demote_recitals(
    fused: list[FusedResult],
    *,
    cap: int = RECITAL_CAP,
    min_rank: int = RECITAL_MIN_RANK,
) -> list[FusedResult]:
    """Operative provisions fill the first `min_rank` positions; recitals then
    re-enter in fused order, at most `cap` of them; the rest go behind
    everything else. Order among operative provisions is unchanged."""
    head = [f for f in fused if not is_recital_result(f)][:min_rank]
    head_ids = {id(f) for f in head}
    out: list[FusedResult] = list(head)
    deferred: list[FusedResult] = []
    admitted = 0
    for f in fused:
        if id(f) in head_ids:
            continue
        if is_recital_result(f):
            if admitted < cap:
                out.append(f)
                admitted += 1
            else:
                deferred.append(f)
        else:
            out.append(f)
    return out + deferred


def retrieve_step(
    session: Session,
    query: str,
    corpus_version_id: int,
    *,
    min_similarity: float = 0.3,
    final_context_size: int = 15,
    raw_query: str | None = None,
    breadth: int = RETRIEVAL_CANDIDATE_BREADTH,
) -> RetrievalStep:
    """`raw_query`, when given and different from `query`, is the user's
    follow-up as typed while `query` is its standalone rewrite: retrieval then
    runs on both and fuses (retrieve_candidates_dual). The plain path never
    passes it, nor a non-default `breadth` (the grader's single widen does)."""
    retrieval_start = time.monotonic()
    if raw_query is not None and raw_query != query:
        all_fused, retrieval_config = retrieve_candidates_dual(
            session,
            raw_query,
            query,
            corpus_version_id,
            min_similarity=min_similarity,
            breadth=breadth,
        )
    else:
        all_fused, retrieval_config = retrieve_candidates(
            session,
            query,
            corpus_version_id,
            min_similarity=min_similarity,
            breadth=breadth,
        )
    retrieval_latency_ms = int((time.monotonic() - retrieval_start) * 1000)
    all_fused = demote_recitals(all_fused)
    served_recitals = sum(is_recital_result(f) for f in all_fused[:final_context_size])
    if served_recitals:
        retrieval_config += f"|recitals={served_recitals}"
    # Equivalent to the old rrf_rank_and_fuse(..., top_k=final_context_size):
    # rrf_rank_and_fuse sorts the full candidate set by rrf_score BEFORE
    # trimming to top_k, and rrf_score doesn't depend on top_k at all - so
    # widening to RETRIEVAL_CANDIDATE_BREADTH and slicing locally yields the
    # identical top final_context_size, in the same order, every time. The
    # actor prior re-sorts that same full list, so the slice still takes the
    # true top final_context_size of the final ordering.
    return RetrievalStep(
        all_fused=all_fused,
        fused=all_fused[:final_context_size],
        retrieval_config=retrieval_config,
        latency_ms=retrieval_latency_ms,
    )


def generate_step(
    query: str,
    fused: list[FusedResult],
    *,
    max_output_tokens: int | None = None,
    extra_instruction: str | None = None,
    parts: list[tuple[str, list[FusedResult]]] | None = None,
    framed_question: str | None = None,
) -> GenerationStep:
    """`extra_instruction`, when given, is appended to the user message (never
    to the system prompt, which is the grounding contract). Only the Stage 3
    verifier's single regeneration passes one; the plain path never does.
    `parts` (Stage 4) groups the context by sub-question; `fused` is then
    their union in prompt order and remains what gets cited."""
    if not fused:
        # Pre-LLM abstention: nothing to ground on, so no call is made.
        return GenerationStep(None, None, None, None)
    prompt = (
        _build_parts_prompt(query, parts)
        if parts
        else _build_user_prompt(query, fused, framed_question)
    )
    if extra_instruction:
        prompt = f"{prompt}\n\n{extra_instruction}"
    generation_start = time.monotonic()
    # Omit max_tokens entirely when unset rather than passing None, so the
    # request body is byte-identical to before for existing callers.
    optional_kwargs = (
        {"max_tokens": max_output_tokens} if max_output_tokens is not None else {}
    )
    try:
        response = _get_client().chat.completions.create(
            model=CHAT_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                # The question is a SEPARATE user message; distinct API roles
                # mean user text cannot structurally replace or edit
                # SYSTEM_PROMPT.
                {"role": "user", "content": prompt},
            ],
            **optional_kwargs,
        )
    except PROVIDER_ERRORS as exc:
        # Generation is the one call a turn cannot proceed without: a clean
        # 503 (app.main), the real error in the server log only.
        log_provider_error("generation", exc)
        raise ProviderUnavailable("generation", exc) from None
    generation_latency_ms = int((time.monotonic() - generation_start) * 1000)
    return GenerationStep(
        answer_text=response.choices[0].message.content,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        latency_ms=generation_latency_ms,
    )


def decide_step(
    session: Session,
    query: str,
    stored_text: str,
    corpus_version_id: int,
    chat_session_id: UUID,
    retrieved: RetrievalStep,
    generated: GenerationStep,
    *,
    final_context_size: int = 15,
    write_trace: bool = True,
    rewrite: "RewriteInfo | None" = None,
    path_tag: str = "",
    system_description: bool = False,
    social: bool = False,
    clarifying: bool = False,
) -> GroundedAnswer:
    """Abstain or answer, persist the turn, write the trace. `path_tag` is
    appended to retrieval_config so the audit log says which execution path
    served the turn (empty for the plain path, "|path=graph" for the graph).
    `system_description` marks an ADR-21 explain-and-route answer."""
    rw = rewrite or RewriteInfo()
    fused = retrieved.fused
    answer_text = generated.answer_text
    if answer_text is None or is_abstention(answer_text):
        # Either retrieval produced no context, or the LLM itself decided the
        # retrieved context didn't actually answer the question. Persist the
        # same shape either way - refusal text, zero citations - not citations
        # for chunks the model just told us were insufficient.
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

    if rw.applied:
        result.rewritten_query = query
    result.system_description = system_description
    result.social = social
    result.clarifying = clarifying

    if write_trace:
        _write_trace_safe(
            session,
            chat_session_id,
            stored_text,
            result,
            corpus_version_id,
            retrieved.latency_ms,
            generated.latency_ms,
            generated.prompt_tokens,
            generated.completion_tokens,
            all_fused=retrieved.all_fused,
            final_context_size=final_context_size,
            retrieval_config=retrieved.retrieval_config + path_tag,
            **rw.trace_fields(query),
        )
    return result


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
    Everything from retrieval onwards is identical either way.

    AGENTIC_RAG=1 (config.agentic_rag_enabled) runs the same three steps as a
    LangGraph graph instead of the sequence below; see app.generation.graph."""
    stored_text = user_text if user_text is not None else query
    if agentic_rag_enabled():
        # Imported here so the plain path never loads LangGraph.
        from app.generation.graph import run_graph

        return run_graph(
            session=session,
            query=query,
            stored_text=stored_text,
            corpus_version_id=corpus_version_id,
            chat_session_id=chat_session_id,
            final_context_size=final_context_size,
            min_similarity=min_similarity,
            write_trace=write_trace,
            max_output_tokens=max_output_tokens,
            rewrite=rewrite,
        )
    retrieved = retrieve_step(
        session,
        query,
        corpus_version_id,
        min_similarity=min_similarity,
        final_context_size=final_context_size,
    )
    generated = generate_step(
        query, retrieved.fused, max_output_tokens=max_output_tokens
    )
    return decide_step(
        session,
        query,
        stored_text,
        corpus_version_id,
        chat_session_id,
        retrieved,
        generated,
        final_context_size=final_context_size,
        write_trace=write_trace,
        rewrite=rewrite,
    )
