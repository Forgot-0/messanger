"""profile photo history + username change

История фото профиля: таблица `profile_photos`, `profiles.photo_id` указывает на
текущее. Варианты фото лежат в приватном бакете под `{user_id}/{photo_id}/`.

Смена username: auth — источник правды, и username в нём уникален без учёта
регистра (`uq_users_username_lower`). `profiles.username` — проекция по событию
`auth.user.username_changed`, поэтому уникальность в профилях снимается (при
переименовании имя ненадолго бывает у двоих), остаётся обычный индекс по
`lower(username)` для поиска.

⚠️ Если в `users` есть имена, различающиеся только регистром, создание
`uq_users_username_lower` упадёт — такие строки нужно развести до миграции.

Revision ID: f4b6d8e0a2c1
Revises: b8d5e27c3f10
Create Date: 2026-10-19 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f4b6d8e0a2c1'
down_revision: Union[str, None] = 'b8d5e27c3f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_photos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("avatars", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("set_main_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_profile_photos_user_order",
        "profile_photos",
        ["user_id", sa.literal_column("set_main_at DESC"), sa.literal_column("id DESC")],
        unique=False,
    )

    op.add_column("profiles", sa.Column("photo_id", sa.UUID(), nullable=True))

    op.drop_constraint("profiles_username_key", "profiles", type_="unique")
    op.create_index(
        "ix_profiles_username_lower",
        "profiles",
        [sa.literal_column("lower(username)")],
        unique=False,
    )
    op.create_index(
        "uq_users_username_lower",
        "users",
        [sa.literal_column("lower(username)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_username_lower", table_name="users")
    op.drop_index("ix_profiles_username_lower", table_name="profiles")
    op.create_unique_constraint("profiles_username_key", "profiles", ["username"])

    op.drop_column("profiles", "photo_id")
    op.drop_index("ix_profile_photos_user_order", table_name="profile_photos")
    op.drop_table("profile_photos")
