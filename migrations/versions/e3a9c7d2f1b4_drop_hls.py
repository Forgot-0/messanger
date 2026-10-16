"""drop HLS state from attachments, drop the duplicate message_id index

Revision ID: e3a9c7d2f1b4
Revises: c5e8a1f4b2d7
Create Date: 2026-10-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e3a9c7d2f1b4'
down_revision: Union[str, None] = 'c5e8a1f4b2d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            'ix_msg_attachments_hls_pending', table_name='message_attachments', postgresql_concurrently=True
        )
        op.drop_index('ix_msg_attachments_source', table_name='message_attachments', postgresql_concurrently=True)
        # Дубль ix_message_attachments_message_id: из начальной миграции его убрали,
        # но в базах, накатанных раньше, он остался.
        op.execute('DROP INDEX CONCURRENTLY IF EXISTS ix_msg_attachments_message_id')

    op.drop_column('message_attachments', 'hls_attempts')
    op.drop_column('message_attachments', 'hls_key')
    op.drop_column('message_attachments', 'hls_status')


def downgrade() -> None:
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

    with op.get_context().autocommit_block():
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
