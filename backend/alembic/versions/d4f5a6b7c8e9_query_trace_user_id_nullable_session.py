"""query_trace: own user_id, nullable chat_session_id

Revision ID: d4f5a6b7c8e9
Revises: c9e1f2a3b4d5
Create Date: 2026-09-22 12:00:00

Deleting a chat must never delete or orphan the quota and audit log. Until
now query_trace reached its user only through chat_session, and the FK was
NOT NULL with NO ACTION, so a session could not be deleted without taking its
traces with it (and its quota count). This migration:

  1. adds query_trace.user_id (FK app_user), backfilled from chat_session,
     then made NOT NULL, with an index for the daily-quota query;
  2. makes query_trace.chat_session_id nullable, so a deleted chat leaves
     its traces in place with the session pointer set to NULL.

Additive for older code paths: the app writes both columns from here on.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f5a6b7c8e9"
down_revision: str | None = "c9e1f2a3b4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("query_trace", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE query_trace qt SET user_id = cs.user_id "
        "FROM chat_session cs WHERE cs.id = qt.chat_session_id AND qt.user_id IS NULL"
    )
    op.alter_column("query_trace", "user_id", nullable=False)
    op.create_foreign_key(
        "fk_query_trace_user", "query_trace", "app_user", ["user_id"], ["id"]
    )
    op.create_index(
        "ix_query_trace_user_created", "query_trace", ["user_id", "created_at"]
    )
    op.alter_column("query_trace", "chat_session_id", nullable=True)


def downgrade() -> None:
    # Traces whose chat was deleted have no session to point at; they must go
    # before the column can be NOT NULL again. This is the one lossy direction.
    op.execute("DELETE FROM retrieval_trace WHERE query_trace_id IN (SELECT id FROM query_trace WHERE chat_session_id IS NULL)")
    op.execute("DELETE FROM query_trace WHERE chat_session_id IS NULL")
    op.alter_column("query_trace", "chat_session_id", nullable=False)
    op.drop_index("ix_query_trace_user_created", table_name="query_trace")
    op.drop_constraint("fk_query_trace_user", "query_trace", type_="foreignkey")
    op.drop_column("query_trace", "user_id")
