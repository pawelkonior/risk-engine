"""Track consistent indexing across the vector and knowledge stores.

Revision ID: 58a20e830cc1
Revises: dac39c4ce2a9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "58a20e830cc1"
down_revision: str | Sequence[str] | None = "dac39c4ce2a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_index_records",
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("collection", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding_profile", sa.String(256), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')", name=op.f("ck_ai_index_records_status")
        ),
        sa.CheckConstraint("chunk_count >= 0", name=op.f("ck_ai_index_records_chunk_count")),
        sa.PrimaryKeyConstraint(
            "namespace", "document_id", "collection", name=op.f("pk_ai_index_records")
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_index_records")
