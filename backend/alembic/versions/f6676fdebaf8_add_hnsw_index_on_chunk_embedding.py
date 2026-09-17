"""add hnsw index on chunk embedding

Revision ID: f6676fdebaf8
Revises: 4d69047b1bb6
Create Date: 2026-09-17 19:04:04.778354

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6676fdebaf8'
down_revision: Union[str, None] = '4d69047b1bb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # vector_cosine_ops must match the <=> cosine-distance operator used in
    # queries, or the index is silently ignored.
    op.execute(
        "CREATE INDEX IF NOT EXISTS chunk_embedding_hnsw_idx "
        "ON chunk USING hnsw (embedding vector_cosine_ops)"
    )
    # Functional GIN index for later hybrid (keyword) search.
    op.execute(
        "CREATE INDEX IF NOT EXISTS chunk_fts_idx "
        "ON chunk USING gin (to_tsvector('english', chunk_text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunk_fts_idx")
    op.execute("DROP INDEX IF EXISTS chunk_embedding_hnsw_idx")
