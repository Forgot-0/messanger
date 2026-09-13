"""per-user chat state on chat_members: pin, archive, notifications mute, draft

Revision ID: c3d9e71b4a52
Revises: b7a1c4f2d8e3
Create Date: 2026-09-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d9e71b4a52'
down_revision: Union[str, None] = 'b7a1c4f2d8e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chat_members', sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('chat_members', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'chat_members',
        sa.Column('notifications_muted_until', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column('chat_members', sa.Column('draft', sa.String(length=4096), nullable=True))
    op.add_column('chat_members', sa.Column('draft_updated_at', sa.DateTime(timezone=True), nullable=True))

    op.create_index(
        'ix_chat_members_user_pinned',
        'chat_members',
        ['user_id', sa.text('pinned_at DESC')],
        unique=False,
        postgresql_where=sa.text('pinned_at IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_chat_members_user_pinned', table_name='chat_members')
    op.drop_column('chat_members', 'draft_updated_at')
    op.drop_column('chat_members', 'draft')
    op.drop_column('chat_members', 'notifications_muted_until')
    op.drop_column('chat_members', 'archived_at')
    op.drop_column('chat_members', 'pinned_at')
