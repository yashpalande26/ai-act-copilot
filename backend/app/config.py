"""Centralised settings for the HTTP surface.

Env was previously read ad-hoc (os.environ inside db/session.py). This step
introduces several related config values - a signing secret, rate limits, model
ceilings - so they get one place rather than being scattered across modules.

Read lazily via functions, NOT at import time: tests and pytest collection must
work without a fully-populated .env, and this repo has a CI history of
import-time KeyError on missing env vars.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# --- limits -------------------------------------------------------------
# Grounded in measured cost at the 15-chunk context (ADR-8, 21 Sep 2026):
# real /ask turns through the production path record ~1,100-1,400 prompt
# tokens and ~260-340 completion tokens. At gpt-4o rates ($2.50/1M in,
# $10/1M out) that is ~$0.006 per call typical and ~$0.0115 worst case with
# output at the 800-token ceiling; the query embedding adds ~$0.000002. At
# the caps below, worst-case exposure is ~$0.23/day/user and ~$1.15/day
# global. Note calls_today() counts every query_trace row, including the
# ones the test_ask_api integration tests write, so the global cap is also
# a budget for test and eval traffic on the same UTC day.
MAX_QUESTION_CHARS = 2000  # ~500 tokens; rejected by Pydantic before any spend
MAX_OUTPUT_TOKENS = 800

PER_MINUTE_LIMIT = "10/minute"  # slowapi burst guard (in-memory)
DAILY_LIMIT_PER_USER_DEFAULT = (
    20  # ~$0.23/day/user worst case at slice 15 (21 Sep 2026)
)
DAILY_LIMIT_GLOBAL_DEFAULT = 100  # circuit breaker: ~$1.15/day total exposure


def daily_limit_per_user() -> int:
    """Per-user daily cap. Env-switchable (22 Sep 2026) so a testing account
    can be raised without a deploy; unset means the measured default."""
    return int(os.environ.get("DAILY_LIMIT_PER_USER", DAILY_LIMIT_PER_USER_DEFAULT))


def daily_limit_global() -> int:
    """Global daily circuit breaker; env-switchable, default as measured."""
    return int(os.environ.get("DAILY_LIMIT_GLOBAL", DAILY_LIMIT_GLOBAL_DEFAULT))


# A 60s token with 10s leeway. The leeway absorbs ordinary NTP drift between
# the Next.js and FastAPI hosts, which would otherwise cause intermittent 401s
# on valid tokens. It widens the replay window to at most 70s - negligible.
SERVICE_TOKEN_ALGORITHM = "HS256"
SERVICE_TOKEN_LEEWAY_SECONDS = 10


# --- environment ----------------------------------------------------------
# Which deployment this process is. Stamped onto every query_trace row so the
# daily quota (deps.calls_today) counts only rows from the SAME environment:
# local dev and pytest can never consume production's budget, and production
# never counts theirs. Defaults to "dev" so a process that was never told
# otherwise cannot label its rows production; production opts in explicitly
# via APP_ENV=production (a Railway service variable). tests/conftest.py
# forces "test". Any other value is refused loudly rather than becoming a
# silent fourth bucket.
APP_ENVIRONMENTS = ("production", "dev", "test")


def app_env() -> str:
    value = os.environ.get("APP_ENV", "dev")
    if value not in APP_ENVIRONMENTS:
        raise RuntimeError(
            f"APP_ENV={value!r} is not one of {APP_ENVIRONMENTS}; refusing to guess."
        )
    return value


# --- free-text extraction (prose -> questionnaire Answers) -------------------
# The one paid call in the assessment path. It fills the form; it never runs
# the engine. Registry key "<provider>:<model>", resolved by extraction.llm.
# gpt-4o-mini by default: the extraction is a bounded mapping task and the
# only key configured today is OpenAI's. CHAT_MODEL (gpt-4o) is unrelated.
MAX_DESCRIPTION_CHARS = 4000  # ~1k tokens; rejected by Pydantic before any spend


def extraction_model() -> str:
    return os.environ.get("EXTRACTION_MODEL", "openai:gpt-4o-mini")


# --- follow-up rewriting (turn 2+ of a chat) --------------------------------
# One small structured call that turns "and for deployers?" into a standalone
# question BEFORE the unchanged retrieval + generation. Part of serving the
# turn: no separate quota row, its tokens land on the turn's query_trace.
def rewrite_model() -> str:
    return os.environ.get("REWRITE_MODEL", "openai:gpt-4o-mini")


def followup_rewrite_enabled() -> bool:
    """OFF by default. The follow-up eval of 22 Sep 2026 passed every hard
    gate (no regression, 0 hallucinated entities, off-corpus left alone) but
    missed the value gate: +12 points of correct-citation over the no-rewrite
    baseline pooled (69% -> 81%), against a required +30. The code stays so
    the gate can be re-run; the live path makes no rewrite call until this
    is set to 1 after a passing run."""
    return os.environ.get("FOLLOWUP_REWRITE", "0") == "1"


def agentic_rag_enabled() -> bool:
    """OFF by default. Stage 0 of the agentic-RAG plan (22 Sep 2026): when set
    to 1, /ask and every eval runner execute the grounded-answer pipeline as a
    LangGraph graph (app.generation.graph) whose nodes call the SAME retrieve,
    generate and decide functions the plain path calls, in the same order,
    with the same result. No node behaves differently yet; the graph exists
    so later stages (query rewriting, retrieval grading, citation
    verification, bounded decomposition) can be added one flag-gated node at
    a time and gated against this baseline."""
    return os.environ.get("AGENTIC_RAG", "0") == "1"


# Stage 1b node default. "1" since the passing run of 22 Sep 2026
# (evals/runs/stage1b_dual.json vs stage0_off.json): multi-turn context
# recall 1.000 held, citation accuracy 0.875 -> 1.000, the coreference
# follow-up answers citing Article 99(4), unanswerable 7/7 refused, 0 drift
# violations, single-hop identical. Only effective when AGENTIC_RAG=1, which
# stays off; AGENTIC_REWRITE=0 restores Stage 0 inside the graph.
AGENTIC_REWRITE_DEFAULT = "1"


def agentic_rewrite_enabled() -> bool:
    """Stage 1: the contextual query-rewrite node at the front of the graph.
    Effective only when the graph runs (AGENTIC_RAG=1); AGENTIC_REWRITE=0
    with the graph on is exactly Stage 0, which is how the node's isolated
    effect is measured. Reuses app.generation.rewrite (gpt-4o-mini, entity
    guard, idempotence, fail-open) and adds the actor-conflict rule and the
    no-retry answerability rule in app.generation.graph."""
    return (
        agentic_rag_enabled()
        and os.environ.get("AGENTIC_REWRITE", AGENTIC_REWRITE_DEFAULT) == "1"
    )


def grade_model() -> str:
    """The retrieval grader's model (Stage 2). Same pluggable interface as
    extraction and rewriting; gpt-4o-mini by default."""
    return os.environ.get("GRADE_MODEL", "openai:gpt-4o-mini")


# Stage 2 node default. "1" since the passing re-gate of 22 Sep 2026 under
# the label-aware faithfulness judge (evals/runs/stage2_grade_j2.json vs
# stage1b_dual_j2.json): pooled context precision 0.713 -> 0.806, single-hop
# and multi-turn recall, citation accuracy, faithfulness and F1_ans unchanged,
# unanswerable 7/7 refused with 6 of them stopped before the gpt-4o call,
# 0 answerable items abstained on. Only effective when AGENTIC_RAG=1, which
# stays off; AGENTIC_GRADE=0 restores Stage 1b inside the graph.
AGENTIC_GRADE_DEFAULT = "1"


def agentic_grade_enabled() -> bool:
    """Stage 2: the retrieval grading node between retrieve and generate
    (app.generation.grade). Effective only inside the graph (AGENTIC_RAG=1).
    The grader gates evidence: proceed, widen once in-corpus, or abstain. It
    never fetches anything outside the corpus and never writes content."""
    return (
        agentic_rag_enabled()
        and os.environ.get("AGENTIC_GRADE", AGENTIC_GRADE_DEFAULT) == "1"
    )


def verify_model() -> str:
    """The post-generation citation verifier's model (Stage 3). ADR-25, 23 Sep
    2026, 46 probes (22 misgrounded traps, 24 valid answers), 3 draws each:
    gpt-4o-mini let a wrong-label claim and a contradiction of an express
    exclusion through 3/3 under every prompt tried (five configurations),
    while gpt-4o caught 22/22 on every draw under every configuration. A
    verifier that passes wrong-provision claims is the worse failure, so
    gpt-4o is the default; VERIFY_MODEL=openai:gpt-4o-mini restores the
    cheaper one. Cost: the verifier call moves from about 0.05 to about 0.8
    cents per verified turn at list prices."""
    return os.environ.get("VERIFY_MODEL", "openai:gpt-4o")


# Stage 3 node default. "1" since the passing run of 22 Sep 2026 with the
# gpt-4o-mini verifier (evals/runs/stage3_verify_mini_j2.json vs
# stage2_grade_j2.json): every deterministic metric identical, no answerable
# item abstained on, probe true positives 11/12 with 0 false positives. Only
# effective when AGENTIC_RAG=1, which stays off.
AGENTIC_VERIFY_DEFAULT = "1"


def agentic_verify_enabled() -> bool:
    """Stage 3: the citation verifier after generation (app.generation.verify).
    Effective only inside the graph (AGENTIC_RAG=1). Every cited claim must be
    entailed by the cited provision in the context; otherwise the answer is
    regenerated ONCE with a grounding instruction and re-verified, and if
    still unsupported the turn abstains. It never adds content."""
    return (
        agentic_rag_enabled()
        and os.environ.get("AGENTIC_VERIFY", AGENTIC_VERIFY_DEFAULT) == "1"
    )


def decompose_model() -> str:
    """The Stage 4 planner's model: splits a compositional question into
    sub-questions. Planning only; the composed answer uses CHAT_MODEL."""
    return os.environ.get("DECOMPOSE_MODEL", "openai:gpt-4o-mini")


# Stage 4 node default. "1" since the passing run of 22 Sep 2026
# (evals/runs/stage4_decompose_j2.json vs stage3_verify_mini_j2.json):
# multi-hop context recall 0.875 -> 1.000, citation accuracy 0.750 -> 1.000,
# F1_ans 0.857 -> 1.000 with the two definition-half refusals now answered;
# single-hop, multi-turn and unanswerable identical; decomposition fired on
# the 8 compositional questions only, at most 2 retrievals per part. Only
# effective when AGENTIC_RAG=1, which stays off.
AGENTIC_DECOMPOSE_DEFAULT = "1"


def agentic_decompose_enabled() -> bool:
    """Stage 4: bounded decomposition of compositional questions
    (app.generation.decompose). Effective only inside the graph
    (AGENTIC_RAG=1). Single-part questions bypass it entirely."""
    return (
        agentic_rag_enabled()
        and os.environ.get("AGENTIC_DECOMPOSE", AGENTIC_DECOMPOSE_DEFAULT) == "1"
    )


# Cross-reference expansion default. "1" since the passing run of 22 Sep 2026
# (evals/runs/stage5_xref_on_j2.json vs stage5_xref_off_j2.json, full agentic
# pipeline both sides): reference-question recall 0.321 -> 1.000 and citation
# accuracy 0.250 -> 0.750, "the requirements set out in Section 2" answered
# with Articles 8 to 15 cited; single-hop, multi-turn and unanswerable
# contexts byte-identical (the expansion fires only on a question that names
# a container or an article); pooled context precision 0.750 -> 0.794.
XREF_EXPANSION_DEFAULT = "1"


def xref_expansion_enabled() -> bool:
    """Cross-reference retrieval expansion (app.retrieval.xref): when the
    question or the top retrieved provisions name a container ("Section 2",
    "Chapter III", "Annex III") or an article ("Article 16", "Articles 9 to
    15"), the target provisions are added to the candidate pool, one hop,
    capped, deterministic. In the SHARED retriever, so the plain and the
    agentic paths both get it. Not tied to AGENTIC_RAG."""
    return os.environ.get("XREF_EXPANSION", XREF_EXPANSION_DEFAULT) == "1"


def understand_model() -> str:
    """The plain-language query-understanding model (ADR-21 Part 1): detects a
    lay description of an AI system and returns Act-vocabulary search terms.
    Search terms only; never a classification."""
    return os.environ.get("UNDERSTAND_MODEL", "openai:gpt-4o-mini")


# Query-understanding default. "1" since the re-gate of 22 Sep 2026 under the
# corrected gold (evals/runs/adr21_final_on_j2.json vs adr21_off_corrected_j2.json):
# plain-language recall 0.500 -> 0.833, citation accuracy 0.333 -> 0.667,
# F1_ans 0.500 -> 0.800, Act-named system types explaining and routing 2 -> 4
# of 5, the un-named use (property valuation) routed with no provision
# asserted, 0 verdict leaks on 47 items, every other bucket identical and
# understanding fired on none of them. Only effective when AGENTIC_RAG=1.
QUERY_UNDERSTANDING_DEFAULT = "1"


def query_understanding_enabled() -> bool:
    """ADR-21: for a plain-language description of an AI system ("a property
    valuation model for bridge lending, how risky is it?") retrieve on
    Act-vocabulary search terms fused with the question, answer in
    explain-and-route mode (what the Act says about that TYPE of system,
    what determines scope, never a verdict on the user's system) and hand
    the classification to the assessment. Effective only inside the graph
    (AGENTIC_RAG=1); legal-term questions are untouched."""
    return (
        agentic_rag_enabled()
        and os.environ.get("QUERY_UNDERSTANDING", QUERY_UNDERSTANDING_DEFAULT) == "1"
    )


def intent_model() -> str:
    return os.environ.get("INTENT_MODEL", "openai:gpt-4o-mini")


# Intent gate default. "1" since the passing run of 22 Sep 2026
# (evals/runs/intent_gate_j2.json and intent_clarify_on_agentic_j2.json vs
# adr21_final_on_j2.json): routing 21/21 across greeting, name, thanks,
# capability, offtopic and disguised-legal buckets; offtopic answered 0;
# disguised-legal misrouted 0; social replies with legal content 0; social and
# offtopic lanes retrieved 0 times; names persisted and recalled 2/2; verdict
# leaks 0; the 47-item on-topic set identical on recall, citation accuracy
# and abstention item by item. Only effective when AGENTIC_RAG=1.
INTENT_GATE_DEFAULT = "1"


def intent_gate_enabled() -> bool:
    """First graph node: gpt-4o-mini classifies the message as social,
    offtopic or on_topic (classify only). Social gets a deterministic
    template and persists an introduced name on the conversation; offtopic
    gets the existing grounded refusal without retrieval; on_topic continues
    unchanged. Any mention of an AI system, the Act, risk or compliance is
    on_topic by deterministic override. Effective inside the graph only."""
    return (
        agentic_rag_enabled()
        and os.environ.get("INTENT_GATE", INTENT_GATE_DEFAULT) == "1"
    )


def clarify_model() -> str:
    return os.environ.get("CLARIFY_MODEL", "openai:gpt-4o-mini")


# Clarifying follow-up default. OFF. ADR-24 (23 Sep 2026) moved the trigger
# to the generator's explain-mode abstention and revised the explain
# instruction; on the 14-sequence clarify set 12 of 13 gates hold (0 leaks,
# 0 stretched provisions, fired only on abstaining system descriptions,
# 4/4 underspecified asked, one question maximum, off-topic never fires). The
# one failing gate: 3/4 underspecified grounded on the second pass; the fourth
# retrieved the gold provision and answered on it, and the gpt-4o-mini
# verifier withheld the answer twice. ADR-25 (same day) moved the verifier to
# gpt-4o with passage headings: the triage reply then grounded in 3 of 4
# draws, and the clarify set was 11 of 13 because the understand step judged
# the vaguest description ("we have an AI model in our company") not a
# system description in both runs. Still not a full pass, so still off; the
# open items are in PROJECT_BRIEF (ADR-24/25 follow-up).
CLARIFY_FOLLOWUP_DEFAULT = "0"


def clarify_followup_enabled() -> bool:
    """ADR-24: when the generator abstains in explain mode on a question
    understood as a plain-language system description (no retrieved
    provision concerns a system of the kind described), ask ONE clarifying
    question (gpt-4o-mini, function of the system: what decision, about
    whom, on what data) instead of the abstention; the reply is retrieved as
    question plus reply through the unchanged path exactly once; whatever
    that pass decides stands (grounded answer, route to the assessment, or
    the grounded refusal for a drifted reply), never a second question. The
    question must name no Article, Annex or legal category and must pass the
    verdict-leak detector, else it is dropped and the turn routes. Effective
    inside the graph only."""
    return (
        agentic_rag_enabled()
        and os.environ.get("CLARIFY_FOLLOWUP", CLARIFY_FOLLOWUP_DEFAULT) == "1"
    )


def chat_model() -> str:
    return os.environ.get("CHAT_LANE_MODEL", "openai:gpt-4o-mini")


def guard_model() -> str:
    return os.environ.get("GUARD_MODEL", "openai:gpt-4o-mini")


# Chat lane default. "1" since the passing run of 22 Sep 2026
# (evals/runs/chat_lane_j2.json and chat_lane_on_agentic_j2.json): general chat
# 7/7 natural with the name recalled, legal statements by the chat lane 0,
# verdict leaks 0 on 64 items, injections blocked 4/4 with 0 passed to the
# chat model and 0 false blocks on 41 on-topic items, the three Act questions
# answered by the rag lane (2 cited, 1 abstained), 40/41 on-topic items
# identical to baseline and the 41st a known generation coin flip (answered
# 5/6 with the lane off, 3/6 on, identical trace path). Only effective when
# AGENTIC_RAG=1, which stays off in production.
CHAT_LANE_DEFAULT = "1"


def chat_lane_enabled() -> bool:
    """ADR-23: the intent gate routes to two lanes, chat and rag. The chat lane
    is gpt-4o-mini with the conversation history: greetings, light
    conversation, common knowledge, the user's idea, clarifying questions, the
    persisted name. It may never state what the Act says; a formed Act
    question is handed to the rag lane as a query. An injection check runs
    before it; the verdict-leak and legal-statement detectors run after it.
    Supersedes the intent gate's templates and offtopic refusal. Effective
    inside the graph only."""
    return (
        agentic_rag_enabled() and os.environ.get("CHAT_LANE", CHAT_LANE_DEFAULT) == "1"
    )


# --- admin allowlist --------------------------------------------------------
# Comma-separated e-mail addresses allowed to read the admin trace viewer
# (/admin/*). Compared, lower-cased, against the e-mail asserted in the
# verified BFF service token. Unset or empty means NO admins: the viewer is
# closed by default in every environment. Set as a Railway service variable
# (and mirrored on Vercel, server-only, purely to hide the link).
def admin_emails() -> frozenset[str]:
    raw = os.environ.get("ADMIN_EMAILS", "")
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def internal_api_secret() -> str:
    """Shared HMAC key for the BFF service token. Server-side only, in BOTH the
    FastAPI env and the Next.js server env - never NEXT_PUBLIC_, never shipped
    to the browser."""
    secret = os.environ.get("INTERNAL_API_SECRET")
    if not secret:
        raise RuntimeError(
            "INTERNAL_API_SECRET is not configured; /ask cannot verify callers."
        )
    return secret
