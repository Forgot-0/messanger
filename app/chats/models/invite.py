import secrets
from datetime import datetime
from typing import Self
from uuid import UUID, uuid7

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.chats.config import chat_config
from app.chats.exceptions import InvalidInviteLinkError, InviteLinkInactiveReason
from app.core.db.base_model import BaseModel, DateMixin
from app.core.utils import now_utc


class ChatInviteLink(BaseModel, DateMixin):
    __tablename__ = "chat_invite_links"

    id: Mapped[UUID] = mapped_column(SAUUID(as_uuid=True), primary_key=True)
    chat_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(
        String(chat_config.INVITE_LINK_NAME_MAX_LENGTH), nullable=True
    )
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usage_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_chat_invite_links_chat_id_id", "chat_id", "id"),
    )

    @classmethod
    def create(
        cls,
        chat_id: UUID,
        created_by: int,
        name: str | None = None,
        expires_at: datetime | None = None,
        usage_limit: int | None = None,
    ) -> Self:
        if expires_at is not None and expires_at <= now_utc():
            raise InvalidInviteLinkError(reason="expires_at_in_past")

        if usage_limit is not None and not (
            1 <= usage_limit <= chat_config.INVITE_LINK_MAX_USAGE_LIMIT
        ):
            raise InvalidInviteLinkError(reason="usage_limit_out_of_range")

        cleaned_name = name.strip() if name is not None else None

        return cls(
            id=uuid7(),
            chat_id=chat_id,
            code=secrets.token_urlsafe(chat_config.INVITE_LINK_CODE_BYTES),
            name=cleaned_name or None,
            created_by=created_by,
            expires_at=expires_at,
            usage_limit=usage_limit,
            usage_count=0,
            revoked_at=None,
        )

    def revoke(self) -> None:
        if self.revoked_at is None:
            self.revoked_at = now_utc()

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= now_utc()

    @property
    def is_exhausted(self) -> bool:
        return self.usage_limit is not None and self.usage_count >= self.usage_limit

    @property
    def inactive_reason(self) -> InviteLinkInactiveReason | None:
        if self.is_revoked:
            return InviteLinkInactiveReason.REVOKED
        if self.is_expired:
            return InviteLinkInactiveReason.EXPIRED
        if self.is_exhausted:
            return InviteLinkInactiveReason.USAGE_LIMIT_REACHED
        return None

    @property
    def is_active(self) -> bool:
        return self.inactive_reason is None
