"""GIN full-text index on messages.content for server-side message search

Revision ID: d4f2a91c60b7
Revises: c3d9e71b4a52
Create Date: 2026-09-13 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd4f2a91c60b7'
down_revision: Union[str, None] = 'c3d9e71b4a52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_messages_content_fts_simple"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX {INDEX_NAME} ON messages "
        f"USING gin (to_tsvector('simple', content))"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX {INDEX_NAME}")
