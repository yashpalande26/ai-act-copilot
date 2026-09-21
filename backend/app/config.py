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
