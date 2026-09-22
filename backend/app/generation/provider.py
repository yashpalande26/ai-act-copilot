"""Model-provider failures (23 Sep 2026). An OpenAI credit exhaustion reached
users as "Something went wrong" with a traceback. Every OpenAI call in the
request path now degrades in one of two ways:

  optional call     the mini calls (rewrite, understand, grade, verify, plan,
                    intent, chat lane, injection guard) already fail open
                    inside their own modules: the turn continues without
                    that step. Nothing here changes that.
  required call     generation, and retrieval when no leg can serve, raise
                    ProviderUnavailable; app.main turns it into a clean 503
                    with a short user-facing message and logs the real error
                    (type, HTTP status, provider error code, stage) server
                    side. The provider message, the key and the traceback
                    never reach the client.

PROVIDER_ERRORS is the SDK's base class, which covers RateLimitError (and the
insufficient_quota code it carries), AuthenticationError and
PermissionDeniedError (APIStatusError), APITimeoutError and
APIConnectionError, and any other APIError subclass.
"""

import logging

import openai

log = logging.getLogger("app.provider")

PROVIDER_ERRORS: tuple[type[BaseException], ...] = (openai.APIError,)

USER_MESSAGE = "The assistant is temporarily unavailable. Please try again in a moment."


class ProviderUnavailable(Exception):
    """A required model-provider call failed; the request cannot proceed."""

    def __init__(self, stage: str, cause: BaseException | None = None):
        super().__init__(stage)
        self.stage = stage
        self.cause = cause


def describe(exc: BaseException) -> str:
    """Diagnostic summary with no secrets: exception type, HTTP status and
    the provider's error code when present. Not the message text, which can
    echo request content."""
    parts = [type(exc).__name__]
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        parts.append(f"status={status_code}")
    body = getattr(exc, "body", None)
    code = None
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        code = err.get("code") or err.get("type") if isinstance(err, dict) else None
    code = code or getattr(exc, "code", None)
    if code:
        parts.append(f"code={code}")
    return " ".join(str(p) for p in parts)


def log_provider_error(stage: str, exc: BaseException) -> None:
    log.error("provider error: stage=%s %s", stage, describe(exc))


def is_provider_error(exc: BaseException) -> bool:
    return isinstance(exc, PROVIDER_ERRORS)
