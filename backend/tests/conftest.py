"""Test-session environment.

Forces APP_ENV=test before any test module (and therefore any app module)
is imported, so every query_trace row a test writes is stamped "test" and
counts only against the test environment's daily quota, never production's.

Assigned, not setdefault: a developer's shell may have APP_ENV=production
exported for a manual check, and that must not leak into the test run.
"""

import os

os.environ["APP_ENV"] = "test"
