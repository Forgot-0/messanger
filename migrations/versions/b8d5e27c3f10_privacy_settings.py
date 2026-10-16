"""privacy settings: profile_privacy + проекции в модуле чатов

Пять осей приватности (кто видит время захода/онлайн и фото профиля, кто может
писать, добавлять в группы и звонить) с персональными исключениями. Модуль чатов
читает только свои проекции: копию настроек в `chat_user_profiles`, исключения в
`chat_user_privacy_exceptions` и адресную книгу в `chat_user_contacts`.

Revision ID: b8d5e27c3f10
Revises: a6b31f08c9d4
Create Date: 2026-10-16 22:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d5e27c3f10'
down_revision: Union[str, None] = 'a6b31f08c9d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VISIBILITY = sa.Enum(
    "everybody", "contacts", "nobody",
    name="privacyvisibility", native_enum=False, length=16,
)
RULE = sa.Enum(
    "last_seen", "photo", "messages", "group_invites", "calls",
    name="privacyrule", native_enum=False, length=16,
)

PRIVACY_COLUMNS = (
    "privacy_last_seen",
    "privacy_photo",
    "privacy_messages",
    "privacy_group_invites",
    "privacy_calls",
)


def upgrade() -> None:
    op.create_table(
        "profile_privacy",
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("last_seen", VISIBILITY, server_default="everybody", nullable=False),
        sa.Column("photo", VISIBILITY, server_default="everybody", nullable=False),
        sa.Column("messages", VISIBILITY, server_default="everybody", nullable=False),
        sa.Column("group_invites", VISIBILITY, server_default="everybody", nullable=False),
        sa.Column("calls", VISIBILITY, server_default="everybody", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "profile_privacy_exceptions",
        sa.Column("owner_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("rule", RULE, nullable=False),
        sa.Column("target_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("allow", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["profile_privacy.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("owner_id", "rule", "target_id"),
    )

    op.create_table(
        "chat_user_contacts",
        sa.Column("owner_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("contact_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("owner_id", "contact_id"),
    )
    op.create_table(
        "chat_user_privacy_exceptions",
        sa.Column("owner_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("rule", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("allow", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("owner_id", "rule", "target_id"),
    )

    for column in PRIVACY_COLUMNS:
        op.add_column(
            "chat_user_profiles",
            sa.Column(
                column, sa.String(length=16), server_default="everybody", nullable=False
            ),
        )
    op.add_column(
        "chat_user_profiles",
        sa.Column("privacy_source_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_user_profiles", "privacy_source_updated_at")
    for column in reversed(PRIVACY_COLUMNS):
        op.drop_column("chat_user_profiles", column)

    op.drop_table("chat_user_privacy_exceptions")
    op.drop_table("chat_user_contacts")
    op.drop_table("profile_privacy_exceptions")
    op.drop_table("profile_privacy")
