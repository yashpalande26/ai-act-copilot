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
# Grounded in measured cost: a 5-chunk context averages ~335 tokens (p95 ~834);
# with the system prompt and question that is ~500 input tokens typical,
# ~1000 p95. At gpt-4o rates ($2.50/1M in, $10/1M out) and an 800-token output
# ceiling, worst case is ~$0.0105 per call and typical ~$0.005.
MAX_QUESTION_CHARS = 2000  # ~500 tokens; rejected by Pydantic before any spend
MAX_OUTPUT_TOKENS = 800

PER_MINUTE_LIMIT = "10/minute"  # slowapi burst guard (in-memory)
DAILY_LIMIT_PER_USER = 100  # ~$1.05/day/user worst case
DAILY_LIMIT_GLOBAL = 2000  # circuit breaker: ~$21/day total exposure

# A 60s token with 10s leeway. The leeway absorbs ordinary NTP drift between
# the Next.js and FastAPI hosts, which would otherwise cause intermittent 401s
# on valid tokens. It widens the replay window to at most 70s - negligible.
SERVICE_TOKEN_ALGORITHM = "HS256"
SERVICE_TOKEN_LEEWAY_SECONDS = 10


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
