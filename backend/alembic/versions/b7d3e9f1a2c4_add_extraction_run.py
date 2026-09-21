"""add extraction_run table and assessment provenance columns

Revision ID: b7d3e9f1a2c4
Revises: 6aa3cd421b84
Create Date: 2026-09-21 23:10:00

Free-text extraction (prose -> questionnaire answers). One new table for the
paid call (quota record + provenance) and two nullable/defaulted columns on
assessment (source, extraction_run_id). Additive: older code keeps writing
assessment rows unchanged (source defaults to "form"). Hand-written on the
6aa3cd421b84 template; touches nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d3e9f1a2c4"
down_revision: str | None = "6aa3cd421b84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extraction_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("corpus_version_id", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("input_chars", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("extracted", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        "ix_extraction_run_user_created",
        "extraction_run",
        ["user_id", "created_at"],
        unique=False,
    )
    op.add_column(
        "assessment",
        sa.Column("source", sa.String(), server_default="form", nullable=False),
    )
    op.add_column(
        "assessment", sa.Column("extraction_run_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_assessment_extraction_run",
        "assessment",
        "extraction_run",
        ["extraction_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_assessment_extraction_run", "assessment", type_="foreignkey")
    op.drop_column("assessment", "extraction_run_id")
    op.drop_column("assessment", "source")
    op.drop_index("ix_extraction_run_user_created", table_name="extraction_run")
    op.drop_table("extraction_run")
