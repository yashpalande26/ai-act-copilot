"""Shared BFF service-token helpers for API tests.

Both /ask and /classify sit behind require_service_token, so the two API test
files need the same token factory. Kept in one module rather than copied, so
a change to the token contract (claims, algorithm, TTL) is made once.

The autouse fixture that sets INTERNAL_API_SECRET to SECRET lives in
conftest.py; these helpers only mint tokens against it.
"""

from datetime import UTC, datetime, timedelta

import jwt

from app import config

SECRET = "test-internal-secret"


def make_token(sub="user-1", email="a@example.com", expires_in=60, secret=SECRET):
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": sub,
            "email": email,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        },
        secret,
        algorithm=config.SERVICE_TOKEN_ALGORITHM,
    )


def auth_headers(**kw):
    return {"Authorization": f"Bearer {make_token(**kw)}"}
