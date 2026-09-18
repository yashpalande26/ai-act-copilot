from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Citation, Message
from app.ingestion.embedder import _get_client
from app.retrieval.search import (
    FusedResult,
    SearchResult,
    keyword_search,
    rrf_rank_and_fuse,
    vector_search,
)

CHAT_MODEL = "gpt-4o"

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
    session: Session, chat_session_id: UUID, content: str, fused: list[FusedResult]
) -> Message:
    try:
        message = Message(session_id=chat_session_id, role="assistant", content=content)
        session.add(message)
        session.flush()  # assigns message.id

        for f in fused:
            session.add(
                Citation(
                    message_id=message.id,
                    chunk_id=f.result.chunk_id,
                    provision_citation_id=f.result.citation_id,
                    quoted_text=f.result.chunk_text,
                )
            )
        session.commit()
        return message
    except Exception:
        session.rollback()
        raise


def generate_grounded_answer(
    session: Session,
    query: str,
    corpus_version_id: int,
    chat_session_id: UUID,
    final_context_size: int = 5,
    min_similarity: float = 0.3,
) -> GroundedAnswer:
    vector_results = vector_search(
        session, query, corpus_version_id, top_k=10, min_similarity=min_similarity
    )
    lexical_results = keyword_search(session, query, corpus_version_id, top_k=10)
    fused = rrf_rank_and_fuse(vector_results, lexical_results, top_k=final_context_size)

    if not fused:
        message = _persist_turn(session, chat_session_id, ABSTENTION_TEXT, fused=[])
        return GroundedAnswer(
            answer=ABSTENTION_TEXT, citations=[], message_id=message.id
        )

    prompt = _build_user_prompt(query, fused)
    response = _get_client().chat.completions.create(
        model=CHAT_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    answer_text = response.choices[0].message.content

    if answer_text.strip() == ABSTENTION_TEXT:
        # The LLM itself decided the retrieved context didn't actually answer
        # the question. Persist the same shape as the pre-LLM abstention -
        # refusal text, zero citations - not citations for chunks the model
        # just told us were insufficient.
        message = _persist_turn(session, chat_session_id, ABSTENTION_TEXT, fused=[])
        return GroundedAnswer(
            answer=ABSTENTION_TEXT, citations=[], message_id=message.id
        )

    message = _persist_turn(session, chat_session_id, answer_text, fused=fused)
    return GroundedAnswer(
        answer=answer_text,
        citations=[f.result for f in fused],
        message_id=message.id,
    )
