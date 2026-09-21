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


def pytest_collection_modifyitems(config, items):
    if os.environ.get(LIVE_OPT_IN) == "1":
        return
    skip = pytest.mark.skip(
        reason=f"live-stack test (real DB + paid OpenAI calls); set {LIVE_OPT_IN}=1"
    )
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
