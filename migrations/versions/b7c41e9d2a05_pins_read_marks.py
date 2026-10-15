"""pinned messages, read receipt marks, system message action

Revision ID: b7c41e9d2a05
Revises: 9d39469ebff8
Create Date: 2026-10-15 20:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7c41e9d2a05'
down_revision: Union[str, None] = '9d39469ebff8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'messages',
        sa.Column(
            'action',
            sa.Enum('MESSAGE_PINNED', name='systemmessageaction', native_enum=False, length=32),
            nullable=True,
        ),
    )

    op.create_table('chat_pinned_messages',
    sa.Column('chat_id', sa.UUID(), nullable=False),
    sa.Column('message_id', sa.UUID(), nullable=False),
    sa.Column('message_seq', sa.BigInteger(), nullable=False),
    sa.Column('pinned_by', sa.BigInteger(), nullable=False),
    sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chat_id', 'message_id')
    )
    op.create_index(
        'ix_chat_pinned_messages_chat_seq', 'chat_pinned_messages', ['chat_id', 'message_seq'], unique=False
    )

    op.create_table('read_receipt_marks',
    sa.Column('chat_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('seq', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chat_id', 'user_id', 'seq')
    )
    op.create_index(
        'ix_read_receipt_marks_read_at_brin', 'read_receipt_marks', ['read_at'],
        unique=False, postgresql_using='brin',
    )


def downgrade() -> None:
    op.drop_index('ix_read_receipt_marks_read_at_brin', table_name='read_receipt_marks', postgresql_using='brin')
    op.drop_table('read_receipt_marks')
    op.drop_index('ix_chat_pinned_messages_chat_seq', table_name='chat_pinned_messages')
    op.drop_table('chat_pinned_messages')
    op.drop_column('messages', 'action')
