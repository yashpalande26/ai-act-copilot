"""Shared slowapi limiter.

Lives in its own module so app.main and the routers import the SAME instance -
slowapi keys its counters on the limiter object, so two instances would mean
two independent (and therefore useless) sets of counters.

Keyed on the authenticated subject where available, falling back to client IP.
Keying on the token subject matters: IP alone would let one user behind a NAT
exhaust everyone's allowance, and would let a single user bypass the limit by
changing IP.

In-memory by design for single-instance v1 - counters reset on restart and are
per-process. That is acceptable for a BURST guard; it is explicitly NOT where
the money control lives (see deps.enforce_daily_quota, which is DB-backed).
Moving to multi-instance means pointing this at Redis via storage_uri.
"""

import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import SERVICE_TOKEN_ALGORITHM


def _subject_or_ip(request: Request) -> str:
    """Best-effort subject extraction for rate-limit keying only.

    Deliberately does NOT verify the signature: this runs before auth, and a
    forged subject can only ever split an attacker's own allowance, never
    escalate access. Authorisation is enforced separately by
    require_service_token. Falls back to IP when no usable token is present.
    """
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        try:
            claims = jwt.decode(
                authorization.removeprefix("Bearer ").strip(),
                options={"verify_signature": False},
                algorithms=[SERVICE_TOKEN_ALGORITHM],
            )
            subject = claims.get("sub")
            if subject:
                return f"sub:{subject}"
        except jwt.PyJWTError:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=_subject_or_ip)
