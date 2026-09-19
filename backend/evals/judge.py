import json

from pydantic import BaseModel

from app.ingestion.embedder import _get_client

JUDGE_MODEL = "gpt-4o-mini"

FAITHFULNESS_SYSTEM_PROMPT = """\
You are an evaluator judging whether an AI-generated answer is faithful to the
provided source context - that is, whether every factual claim in the answer
is actually supported by that context, with no hallucinated or unsupported
claims.

You will be given the ANSWER and the CONTEXT it was supposed to be grounded
in. You do not have access to the original question - judge faithfulness to
the context only, not correctness or relevance.

Score from 1 to 5:
5 = every claim in the answer is directly supported by the context
4 = nearly all claims are supported, with at most one minor unsupported detail
3 = mostly supported, but at least one claim is unsupported or not verifiable from the context
2 = significant portions of the answer are not supported by the context
1 = the answer is mostly unsupported by, or contradicts, the context

Think through your reasoning first, then decide the score. Respond with ONLY
strict JSON, no other text, in this exact shape:
{"rationale": "<one or two sentences explaining your reasoning>", "score": <integer 1-5>}
"""

RELEVANCE_SYSTEM_PROMPT = """\
You are an evaluator judging whether an AI-generated answer actually
addresses the question that was asked - regardless of whether the answer is
factually correct or well-supported by any source material.

You will be given the QUESTION and the ANSWER. You do not have access to any
source context - judge only whether the answer is responsive to the
question, not its truthfulness.

Score from 1 to 5:
5 = directly and completely addresses the question asked
4 = addresses the question with minor omissions or slight drift
3 = partially addresses the question, or addresses a related but different question
2 = mostly does not address the question asked
1 = does not address the question at all

Think through your reasoning first, then decide the score. Respond with ONLY
strict JSON, no other text, in this exact shape:
{"rationale": "<one or two sentences explaining your reasoning>", "score": <integer 1-5>}
"""


class JudgeResult(BaseModel):
    score: int
    rationale: str


def _call_judge(system_prompt: str, user_prompt: str) -> JudgeResult:
    response = _get_client().chat.completions.create(
        model=JUDGE_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = response.choices[0].message.content
    try:
        text = (
            (raw or "")
            .strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        data = json.loads(text)
        score = int(data["score"])
        rationale = str(data["rationale"])
        if not 1 <= score <= 5:
            raise ValueError(f"score out of range: {score}")
        return JudgeResult(score=score, rationale=rationale)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        return JudgeResult(
            score=0, rationale=f"PARSE_FAILURE: {exc} (raw: {raw!r:.200})"
        )


def judge_faithfulness(answer: str, context_chunks: list[str]) -> JudgeResult:
    """Judge sees ONLY the answer + the retrieved context - never the question."""
    context_block = "\n\n".join(context_chunks)
    user_prompt = f"ANSWER:\n{answer}\n\nCONTEXT:\n{context_block}"
    return _call_judge(FAITHFULNESS_SYSTEM_PROMPT, user_prompt)


def judge_answer_relevance(question: str, answer: str) -> JudgeResult:
    """Judge sees ONLY the question + the answer - never the context."""
    user_prompt = f"QUESTION:\n{question}\n\nANSWER:\n{answer}"
    return _call_judge(RELEVANCE_SYSTEM_PROMPT, user_prompt)


def mean_score(results: list[JudgeResult]) -> float:
    valid = [
        r.score for r in results if r.score >= 1
    ]  # excludes parse-failure sentinel (0)
    return sum(valid) / len(valid) if valid else 0.0


def pass_at_4_rate(results: list[JudgeResult]) -> float:
    valid = [r for r in results if r.score >= 1]
    return sum(1 for r in valid if r.score >= 4) / len(valid) if valid else 0.0
