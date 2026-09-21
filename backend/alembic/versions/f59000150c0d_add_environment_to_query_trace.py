"""add environment to query_trace

Revision ID: f59000150c0d
Revises: d0522492c752
Create Date: 2026-09-21 11:03:54.834824

Stamps every query_trace row with the environment that wrote it, so the
daily quota (app.api.deps.calls_today) can count only rows from the current
environment. Local dev and pytest share this database with production, and
before this column their rows consumed production's DAILY_LIMIT_GLOBAL.

Backfill: server_default='dev' labels every pre-existing row at the moment
the column lands (a catalog-only change on Postgres 11+, no table rewrite).
Nothing predates production, so no row can be wrongly 'production'. The
UPDATE then relabels the rows written by the pytest live-stack tests, which
are identifiable by their throwaway account names, as 'test'.

NOTE: autogenerate also proposed dropping chunk_embedding_hnsw_idx and
chunk_fts_idx here - the same false positive documented in d0522492c752
(hand-created indexes the models never declare). Removed; this migration
is additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f59000150c0d"
down_revision: str | None = "d0522492c752"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "query_trace",
        sa.Column("environment", sa.String(), server_default="dev", nullable=False),
    )
    op.execute(
        """
        UPDATE query_trace AS qt
        SET environment = 'test'
        FROM chat_session AS cs
        JOIN app_user AS u ON u.id = cs.user_id
        WHERE qt.chat_session_id = cs.id
          AND (u.email LIKE 'ask-it-%' OR u.email LIKE 'integration-test-%')
        """
    )


def downgrade() -> None:
    op.drop_column("query_trace", "environment")
