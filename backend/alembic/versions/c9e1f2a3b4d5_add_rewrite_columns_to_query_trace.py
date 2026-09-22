"""add follow-up rewrite columns to query_trace

Revision ID: c9e1f2a3b4d5
Revises: b7d3e9f1a2c4
Create Date: 2026-09-22 10:00:00

Multi-turn follow-ups: on turn 2+ the user's message may be rewritten into a
standalone question before the unchanged retrieval + generation. The trace
records both (query_text = what the user typed, rewritten_query = what ran)
and the rewrite's token cost. Additive, all nullable; older code keeps
writing rows unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e1f2a3b4d5"
down_revision: str | None = "b7d3e9f1a2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("query_trace", sa.Column("rewritten_query", sa.Text(), nullable=True))
    op.add_column(
        "query_trace", sa.Column("rewrite_prompt_tokens", sa.Integer(), nullable=True)
    )
    op.add_column(
        "query_trace",
        sa.Column("rewrite_completion_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("query_trace", "rewrite_completion_tokens")
    op.drop_column("query_trace", "rewrite_prompt_tokens")
    op.drop_column("query_trace", "rewritten_query")
