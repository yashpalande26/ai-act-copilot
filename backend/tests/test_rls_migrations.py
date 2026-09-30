"""Drift guard: every table the app defines has RLS enabled by a migration.

Static, no database: it reads the migration files as text. RLS on Supabase
was first switched on by hand; migration f7a8b9c0d1e2 records it. Without
this test, a new ORM table would ship with RLS off and sit open to the
Supabase Data API until someone noticed. The fix when it fails is a new
migration with `ALTER TABLE IF EXISTS public.<table> ENABLE ROW LEVEL
SECURITY` for the new table.
"""

import re
from pathlib import Path

import app.db.models  # noqa: F401 - registers every table on Base.metadata
from app.db.base import Base

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"

ENABLE_RLS = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?(\w+)\s+"
    r"ENABLE\s+ROW\s+LEVEL\s+SECURITY",
    re.IGNORECASE,
)


def _tables_with_rls() -> set[str]:
    found: set[str] = set()
    for path in VERSIONS.glob("*.py"):
        found.update(ENABLE_RLS.findall(path.read_text(encoding="utf-8")))
    return found


def test_every_table_has_rls_enabled_in_a_migration():
    expected = set(Base.metadata.tables) | {"alembic_version"}
    missing = sorted(expected - _tables_with_rls())
    assert not missing, (
        f"No ENABLE ROW LEVEL SECURITY migration for: {missing}. "
        "Add one in a new Alembic migration."
    )


def test_scan_is_not_vacuous():
    # If the pattern or the folder path broke, the guard above would still
    # pass when metadata were empty; pin both ends to known tables.
    assert {"alembic_version", "query_trace"} <= _tables_with_rls()
    assert "query_trace" in Base.metadata.tables
