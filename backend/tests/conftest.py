"""Test-session environment and the live-stack opt-in.

APP_ENV
    Forced to "test" before any test module (and therefore any app module)
    is imported, so every query_trace row a test writes is stamped "test" and
    counts only against the test environment's daily quota, never
    production's. Assigned, not setdefault: a developer's shell may have
    APP_ENV=production exported for a manual check, and that must not leak
    into the test run.

RUN_LIVE_TESTS
    Tests marked @pytest.mark.live hit the real database and the real OpenAI
    API (measured: 3 chat-model calls and 3 embedding calls per run). They are skipped
    unless RUN_LIVE_TESTS=1 is set explicitly, so a plain `pytest` never
    spends money even when a key is present:

        pytest                        # live tests skipped, zero API calls
        RUN_LIVE_TESTS=1 pytest       # live tests run (needs the keys too)
        RUN_LIVE_TESTS=1 pytest -m live   # only the live tests

    The tests keep their own key checks for the case where the opt-in is set
    but a key is missing.
"""

import os

import pytest

os.environ["APP_ENV"] = "test"

LIVE_OPT_IN = "RUN_LIVE_TESTS"


@pytest.fixture(autouse=True)
def _service_secret(monkeypatch):
    """Every authenticated endpoint (/ask, /classify) verifies tokens against
    INTERNAL_API_SECRET; tests mint theirs with tests._auth.SECRET."""
    from tests._auth import SECRET

    monkeypatch.setenv("INTERNAL_API_SECRET", SECRET)


@pytest.fixture(autouse=True)
def _lane_flags_off(monkeypatch):
    """INTENT_GATE and CLARIFY_FOLLOWUP are on by default inside the graph;
    a unit test that does not set them must never make the gate's real
    classification call. Tests that exercise them set them explicitly (a
    later setenv in the test body wins)."""
    monkeypatch.setenv("INTENT_GATE", "0")
    monkeypatch.setenv("CLARIFY_FOLLOWUP", "0")
    monkeypatch.setenv("CHAT_LANE", "0")


@pytest.fixture(autouse=True)
def _reset_limiter():
    """slowapi counters persist on the module-level Limiter, so one test's
    requests would otherwise 429 the next. Global because both /ask and
    /classify are rate-limited."""
    from app.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


def pytest_collection_modifyitems(config, items):
    if os.environ.get(LIVE_OPT_IN) == "1":
        return
    skip = pytest.mark.skip(
        reason=f"live-stack test (real DB + paid OpenAI calls); set {LIVE_OPT_IN}=1"
    )
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
