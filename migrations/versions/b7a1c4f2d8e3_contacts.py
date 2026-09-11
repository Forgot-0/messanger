"""user contacts, identifiers, pending contacts, blocked users; contacts -> profile_links

Revision ID: b7a1c4f2d8e3
Revises: 90fc8bac0ea3
Create Date: 2026-09-10 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7a1c4f2d8e3'
down_revision: Union[str, None] = '90fc8bac0ea3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Соц-ссылки профиля переезжают в profile_links: имя contact закреплено
    # за адресной книгой.
    op.rename_table('contacts', 'profile_links')
    op.execute('ALTER INDEX ix_contacts_profile_id RENAME TO ix_profile_links_profile_id')
    op.execute('ALTER SEQUENCE contacts_id_seq RENAME TO profile_links_id_seq')
    op.execute('ALTER TABLE profile_links RENAME CONSTRAINT contacts_pkey TO profile_links_pkey')

    op.create_table(
        'user_contacts',
        sa.Column('owner_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('contact_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('first_name', sa.String(length=64), nullable=True),
        sa.Column('last_name', sa.String(length=64), nullable=True),
        sa.Column('source', sa.SmallInteger(), nullable=False),
        sa.Column('is_mutual', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_favorite', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('owner_id', 'contact_id'),
    )
    op.create_index('ix_user_contacts_contact_owner', 'user_contacts', ['contact_id', 'owner_id'], unique=False)
    op.create_index('ix_user_contacts_owner_updated', 'user_contacts', ['owner_id', 'updated_at'], unique=False)

    op.create_table(
        'user_identifiers',
        sa.Column('identifier_hash', sa.LargeBinary(), nullable=False),
        sa.Column('kind', sa.SmallInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('identifier_hash'),
    )
    op.create_index(op.f('ix_user_identifiers_user_id'), 'user_identifiers', ['user_id'], unique=False)

    op.create_table(
        'pending_contacts',
        sa.Column('owner_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('identifier_hash', sa.LargeBinary(), nullable=False),
        sa.Column('first_name', sa.String(length=64), nullable=True),
        sa.Column('last_name', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('owner_id', 'identifier_hash'),
    )
    op.create_index('ix_pending_contacts_identifier', 'pending_contacts', ['identifier_hash'], unique=False)

    op.create_table(
        'blocked_users',
        sa.Column('owner_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('target_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('owner_id', 'target_id'),
    )


def downgrade() -> None:
    op.drop_table('blocked_users')
    op.drop_index('ix_pending_contacts_identifier', table_name='pending_contacts')
    op.drop_table('pending_contacts')
    op.drop_index(op.f('ix_user_identifiers_user_id'), table_name='user_identifiers')
    op.drop_table('user_identifiers')
    op.drop_index('ix_user_contacts_owner_updated', table_name='user_contacts')
    op.drop_index('ix_user_contacts_contact_owner', table_name='user_contacts')
    op.drop_table('user_contacts')

    op.execute('ALTER TABLE profile_links RENAME CONSTRAINT profile_links_pkey TO contacts_pkey')
    op.execute('ALTER SEQUENCE profile_links_id_seq RENAME TO contacts_id_seq')
    op.execute('ALTER INDEX ix_profile_links_profile_id RENAME TO ix_contacts_profile_id')
    op.rename_table('profile_links', 'contacts')
