"""Row Level Security on every public table (housekeeping, 30 Sep 2026).

RLS was switched on by hand in the Supabase dashboard; this records it in the
migration history so a fresh database (local compose, CI, a rebuilt Supabase
project) gets the same state. Idempotent: ENABLE on a table that already has
it is a no-op. No policies are added on purpose: with RLS on and no policy,
Supabase's Data API roles (anon, authenticated) read and write nothing, while
the backend's table-owning role is unaffected (owners bypass RLS unless it is
FORCEd).

The table list is hardcoded, not read from Base.metadata: a migration must
reproduce the same statements forever, whatever the models later become.
tests/test_rls_migrations.py fails when an ORM table has no ENABLE statement
in any migration, so a new table needs its own line in its own migration.

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
"""

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

# One literal statement per table, so the drift-guard test can find each one.
STATEMENTS = (
    "ALTER TABLE IF EXISTS public.alembic_version ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.app_user ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.assessment ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.chat_session ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.chunk ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.citation ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.classification_run ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.corpus_version ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.extraction_run ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.message ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.provision ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.provision_reference ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.query_trace ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE IF EXISTS public.retrieval_trace ENABLE ROW LEVEL SECURITY",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # Deliberately a no-op. Disabling RLS would reopen every table to the
    # Supabase Data API (anyone holding the project's public anon key could
    # read and write it), and RLS was on before this migration existed, so
    # "undoing" it would not restore the prior state anyway.
    pass
