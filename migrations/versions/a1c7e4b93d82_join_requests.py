"""chat join requests, request-only invite links, join_by_request

Revision ID: a1c7e4b93d82
Revises: f4b6d8e0a2c1
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1c7e4b93d82'
down_revision: Union[str, None] = 'f4b6d8e0a2c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'chats',
        sa.Column('join_by_request', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.add_column(
        'chat_invite_links',
        sa.Column(
            'creates_join_request', sa.Boolean(), server_default=sa.text('false'), nullable=False
        ),
    )

    op.create_table('chat_join_requests',
    sa.Column('chat_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('invite_link_id', sa.UUID(), nullable=True),
    sa.Column(
        'status',
        sa.Enum('PENDING', 'APPROVED', 'DECLINED', name='joinrequeststatus', native_enum=False, length=16),
        nullable=False,
    ),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['invite_link_id'], ['chat_invite_links.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('chat_id', 'user_id')
    )
    op.create_index('ix_chat_join_requests_user', 'chat_join_requests', ['user_id'], unique=False)
    op.execute(
        "CREATE INDEX ix_chat_join_requests_pending ON chat_join_requests "
        "(chat_id, requested_at DESC, user_id DESC) WHERE resolved_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_join_requests_pending")
    op.drop_index('ix_chat_join_requests_user', table_name='chat_join_requests')
    op.drop_table('chat_join_requests')
    op.drop_column('chat_invite_links', 'creates_join_request')
    op.drop_column('chats', 'join_by_request')
