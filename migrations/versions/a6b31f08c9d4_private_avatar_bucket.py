"""private avatar bucket: store S3 keys instead of public URLs

Бакет аватаров профиля стал приватным (Policy.NONE), ссылки теперь подписываются
на чтении. Пока он был публичным, `upload_file` возвращал абсолютный URL, и он
уезжал и в `profiles.avatars`, и — через событие `profiles.profile.*` — в проекцию
`chat_user_profiles.avatar_s3_key`. Такие строки больше не открываются анонимно,
поэтому переводим их в ключи объектов.

Revision ID: a6b31f08c9d4
Revises: e3a9c7d2f1b4
Create Date: 2026-10-16 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

from app.core.configs.app import app_config
from app.profiles.config import profile_config

# revision identifiers, used by Alembic.
revision: str = 'a6b31f08c9d4'
down_revision: Union[str, None] = 'e3a9c7d2f1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BUCKET = profile_config.AVATAR_BUCKET
URL_PREFIX_RE = f'^https?://[^/]+/{BUCKET}/'
PUBLIC_PREFIX = f'{app_config.storage_public_endpoint_url}/{BUCKET}/'


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE profiles
        SET avatars = coalesce(
            (
                SELECT jsonb_object_agg(size_key, stripped)
                FROM jsonb_each(avatars) AS sizes(size_key, variants),
                LATERAL (
                    SELECT CASE
                        WHEN jsonb_typeof(variants) <> 'object' THEN variants
                        ELSE coalesce(
                            (
                                SELECT jsonb_object_agg(
                                    fmt,
                                    to_jsonb(regexp_replace(value #>> '{{}}', '{URL_PREFIX_RE}', ''))
                                )
                                FROM jsonb_each(variants) AS formats(fmt, value)
                            ),
                            variants
                        )
                    END AS stripped
                ) AS cleaned
            ),
            '{{}}'::jsonb
        )
        WHERE avatars::text LIKE '%http%'
        """
    )
    op.execute(
        f"""
        UPDATE chat_user_profiles
        SET avatar_s3_key = regexp_replace(avatar_s3_key, '{URL_PREFIX_RE}', '')
        WHERE avatar_s3_key LIKE 'http%'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE profiles
        SET avatars = coalesce(
            (
                SELECT jsonb_object_agg(size_key, restored)
                FROM jsonb_each(avatars) AS sizes(size_key, variants),
                LATERAL (
                    SELECT CASE
                        WHEN jsonb_typeof(variants) <> 'object' THEN variants
                        ELSE coalesce(
                            (
                                SELECT jsonb_object_agg(
                                    fmt,
                                    to_jsonb('{PUBLIC_PREFIX}' || (value #>> '{{}}'))
                                )
                                FROM jsonb_each(variants) AS formats(fmt, value)
                            ),
                            variants
                        )
                    END AS restored
                ) AS rebuilt
            ),
            '{{}}'::jsonb
        )
        WHERE avatars <> '{{}}'::jsonb AND avatars::text NOT LIKE '%http%'
        """
    )
    op.execute(
        f"""
        UPDATE chat_user_profiles
        SET avatar_s3_key = '{PUBLIC_PREFIX}' || avatar_s3_key
        WHERE avatar_s3_key IS NOT NULL AND avatar_s3_key NOT LIKE 'http%'
        """
    )
