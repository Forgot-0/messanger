"""attachment previews, thumbhash, HLS state, shared media and link indexes

Revision ID: c5e8a1f4b2d7
Revises: b7c41e9d2a05
Create Date: 2026-10-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c5e8a1f4b2d7'
down_revision: Union[str, None] = 'b7c41e9d2a05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('message_attachments', sa.Column('message_seq', sa.BigInteger(), nullable=True))
    op.add_column('message_attachments', sa.Column('thumbhash', sa.String(length=64), nullable=True))
    op.add_column(
        'message_attachments',
        sa.Column('previews', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'message_attachments',
        sa.Column(
            'hls_status',
            sa.Enum('PENDING', 'READY', 'FAILED', name='hlsstatus', native_enum=False, length=16),
            nullable=True,
        ),
    )
    op.add_column('message_attachments', sa.Column('hls_key', sa.String(length=512), nullable=True))
    op.add_column(
        'message_attachments',
        sa.Column('hls_attempts', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    )
    op.add_column(
        'messages',
        sa.Column('has_links', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )

    op.execute(
        "UPDATE message_attachments AS a SET message_seq = m.seq "
        "FROM messages AS m WHERE m.id = a.message_id AND a.message_seq IS NULL"
    )
    # Та же регулярка, что Message.contains_link и линкифаер клиента.
    op.execute(
        "UPDATE messages SET has_links = true "
        "WHERE content ~* '(https?://|www\\.)[^\\s<>\"'']'"
    )

    # Таблицы горячие: индексы строятся без блокировки записи.
    with op.get_context().autocommit_block():
        op.create_index(
            'ix_msg_attachments_shared_media', 'message_attachments',
            ['chat_id', 'attachment_type', 'message_seq', 'id'],
            unique=False, postgresql_where=sa.text('message_seq IS NOT NULL'),
            postgresql_concurrently=True,
        )
        op.create_index(
            'ix_msg_attachments_source', 'message_attachments', ['source_attachment_id'],
            unique=False, postgresql_where=sa.text('source_attachment_id IS NOT NULL'),
            postgresql_concurrently=True,
        )
        op.create_index(
            'ix_msg_attachments_hls_pending', 'message_attachments', ['updated_at'],
            unique=False, postgresql_where=sa.text("hls_status = 'PENDING'"),
            postgresql_concurrently=True,
        )
        op.create_index(
            'ix_messages_chat_links', 'messages', ['chat_id', 'seq'],
            unique=False, postgresql_where=sa.text('has_links AND is_deleted = false'),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index('ix_messages_chat_links', table_name='messages', postgresql_concurrently=True)
        op.drop_index(
            'ix_msg_attachments_hls_pending', table_name='message_attachments', postgresql_concurrently=True
        )
        op.drop_index('ix_msg_attachments_source', table_name='message_attachments', postgresql_concurrently=True)
        op.drop_index(
            'ix_msg_attachments_shared_media', table_name='message_attachments', postgresql_concurrently=True
        )

    op.drop_column('messages', 'has_links')
    op.drop_column('message_attachments', 'hls_attempts')
    op.drop_column('message_attachments', 'hls_key')
    op.drop_column('message_attachments', 'hls_status')
    op.drop_column('message_attachments', 'previews')
    op.drop_column('message_attachments', 'thumbhash')
    op.drop_column('message_attachments', 'message_seq')
