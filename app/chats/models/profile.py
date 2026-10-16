from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    DateTime,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel, DateMixin
from app.core.privacy import DEFAULT_VISIBILITY, PrivacyRule, PrivacyVisibility


def _privacy_column() -> Mapped[str]:
    return mapped_column(
        String(16),
        default=DEFAULT_VISIBILITY.value,
        server_default=DEFAULT_VISIBILITY.value,
        nullable=False,
    )


class ChatUserProfile(BaseModel, DateMixin):
    __tablename__ = "chat_user_profiles"

    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, primary_key=True, autoincrement=False
    )

    username: Mapped[str | None] = mapped_column(String, nullable=True)

    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_s3_key: Mapped[str | None] = mapped_column(String, nullable=True)

    last_event_id: Mapped[UUID | None] = mapped_column(SAUUID(as_uuid=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    privacy_last_seen: Mapped[str] = _privacy_column()
    privacy_photo: Mapped[str] = _privacy_column()
    privacy_messages: Mapped[str] = _privacy_column()
    privacy_group_invites: Mapped[str] = _privacy_column()
    privacy_calls: Mapped[str] = _privacy_column()

    privacy_source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @staticmethod
    def privacy_column_name(rule: PrivacyRule) -> str:
        return f"privacy_{rule.value}"

    def visibility(self, rule: PrivacyRule) -> PrivacyVisibility:
        return ChatUserProfile.parse_visibility(
            getattr(self, ChatUserProfile.privacy_column_name(rule))
        )

    @staticmethod
    def parse_visibility(value: str | None) -> PrivacyVisibility:
        if value is None:
            return PrivacyVisibility.NOBODY

        try:
            return PrivacyVisibility(value)
        except ValueError:
            return PrivacyVisibility.NOBODY

    @classmethod
    def create(
        cls,
        user_id: int,
        username: str | None,
        display_name: str | None = None,
        avatar_s3_key: str | None = None,
        last_event_id: UUID | None = None,
        source_updated_at: datetime | None = None,
    ) -> ChatUserProfile:
        instance = cls(
            user_id=user_id,
            username=username,
            display_name=display_name,
            avatar_s3_key=avatar_s3_key,
            last_event_id=last_event_id,
            source_updated_at=source_updated_at,
        )
        return instance
