"""chat_session: display_name and pending_clarification (intent gate and
clarifying follow-up, 22 Sep 2026). Both nullable, additive; downgrade drops
them (the name and any pending marker are lost, nothing else).

Revision ID: e5f6a7b8c9d0
Revises: d4f5a6b7c8e9
"""

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4f5a6b7c8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_session", sa.Column("display_name", sa.String(), nullable=True))
    op.add_column(
        "chat_session", sa.Column("pending_clarification", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_session", "pending_clarification")
    op.drop_column("chat_session", "display_name")
