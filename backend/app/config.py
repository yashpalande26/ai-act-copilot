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
DAILY_LIMIT_PER_USER = 20  # ~$0.23/day/user worst case at slice 15 (21 Sep 2026)
DAILY_LIMIT_GLOBAL = 100  # circuit breaker: ~$1.15/day total exposure

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
