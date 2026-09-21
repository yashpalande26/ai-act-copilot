"""add assessment table

Revision ID: 6aa3cd421b84
Revises: f59000150c0d
Create Date: 2026-09-21 19:27:07.495307

Saved assessments: the user's answers plus the decision the deterministic
engine produced from them, stamped with engine_version, the corpus
consolidated date and the environment. Additive: one new table, one index.

NOTE: autogenerate again proposed dropping chunk_embedding_hnsw_idx and
chunk_fts_idx (hand-created indexes the models never declare; see
d0522492c752). Removed; this migration touches nothing but `assessment`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6aa3cd421b84"
down_revision: str | None = "f59000150c0d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assessment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("corpus_version_id", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("engine_version", sa.String(), nullable=False),
        sa.Column("corpus_consolidated_date", sa.String(), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("headline", sa.String(), nullable=False),
        sa.Column("roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "obligation_citation_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("penalties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["corpus_version_id"], ["corpus_version.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assessment_user_created",
        "assessment",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_assessment_user_created", table_name="assessment")
    op.drop_table("assessment")
