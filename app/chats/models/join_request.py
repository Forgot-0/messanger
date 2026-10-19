from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self
from uuid import UUID

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.chats.config import chat_config
from app.chats.exceptions import JoinRequestPendingError, JoinRequestRetryLaterError
from app.core.db.base_model import BaseModel
from app.core.events.event import BaseEvent
from app.core.utils import now_utc


class JoinRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"


@dataclass(frozen=True)
class CreatedChatJoinRequestEvent(BaseEvent):
    chat_id: str
    user_id: int
    invite_link_id: str | None
    requested_at: str

    __event_name__ = "chats.join_request.created"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class ApprovedChatJoinRequestEvent(BaseEvent):
    chat_id: str
    user_id: int
    resolved_by: int
    role_id: int

    __event_name__ = "chats.join_request.approved"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class DeclinedChatJoinRequestEvent(BaseEvent):
    chat_id: str
    user_id: int
    resolved_by: int

    __event_name__ = "chats.join_request.declined"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class CancelledChatJoinRequestEvent(BaseEvent):
    chat_id: str
    user_id: int

    __event_name__ = "chats.join_request.cancelled"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


class ChatJoinRequest(BaseModel):
    """Заявка на вступление в чат.

    Строка одна на пару (chat_id, user_id) и переживает решение модератора:
    по ней считается кулдаун повторной заявки, а история «одобрен/отклонён»
    остаётся видна админам. «Ожидает решения» — это `resolved_at IS NULL`:
    именно в такой форме предикат попадает и в partial-индекс
    `ix_chat_join_requests_pending`, и в запросы (см. инвариант про
    совпадение предикатов).
    """

    __tablename__ = "chat_join_requests"

    chat_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    invite_link_id: Mapped[UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("chat_invite_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[JoinRequestStatus] = mapped_column(
        SAEnum(JoinRequestStatus, native_enum=False, length=16), nullable=False
    )

    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    resolved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)

    __table_args__ = (
        Index(
            "ix_chat_join_requests_pending",
            "chat_id",
            text("requested_at DESC"),
            text("user_id DESC"),
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index("ix_chat_join_requests_user", "user_id"),
    )

    @classmethod
    def create(cls, chat_id: UUID, user_id: int, invite_link_id: UUID | None = None) -> Self:
        instance = cls(
            chat_id=chat_id,
            user_id=user_id,
            invite_link_id=invite_link_id,
            status=JoinRequestStatus.PENDING,
            requested_at=now_utc(),
        )
        instance._register_created()
        return instance

    @property
    def is_pending(self) -> bool:
        return self.resolved_at is None

    @property
    def retry_at(self) -> datetime | None:
        if self.status != JoinRequestStatus.DECLINED or self.resolved_at is None:
            return None
        return self.resolved_at + timedelta(seconds=chat_config.JOIN_REQUEST_RETRY_AFTER_SECONDS)

    def renew(self, invite_link_id: UUID | None = None) -> None:
        """Повторная заявка по уже существующей строке."""
        if self.is_pending:
            raise JoinRequestPendingError(chat_id=str(self.chat_id), user_id=self.user_id)

        retry_at = self.retry_at
        if retry_at is not None and retry_at > now_utc():
            raise JoinRequestRetryLaterError(
                chat_id=str(self.chat_id),
                user_id=self.user_id,
                retry_after=int((retry_at - now_utc()).total_seconds()) + 1,
            )

        self.invite_link_id = invite_link_id
        self.status = JoinRequestStatus.PENDING
        self.requested_at = now_utc()
        self.resolved_at = None
        self.resolved_by = None
        self._register_created()

    def approve(self, resolved_by: int, role_id: int) -> None:
        self._resolve(JoinRequestStatus.APPROVED, resolved_by)
        self.register_event(
            ApprovedChatJoinRequestEvent(
                chat_id=str(self.chat_id),
                user_id=self.user_id,
                resolved_by=resolved_by,
                role_id=int(role_id),
            )
        )

    def decline(self, resolved_by: int) -> None:
        self._resolve(JoinRequestStatus.DECLINED, resolved_by)
        self.register_event(
            DeclinedChatJoinRequestEvent(
                chat_id=str(self.chat_id),
                user_id=self.user_id,
                resolved_by=resolved_by,
            )
        )

    def cancel(self) -> None:
        self.register_event(
            CancelledChatJoinRequestEvent(chat_id=str(self.chat_id), user_id=self.user_id)
        )

    def _resolve(self, status: JoinRequestStatus, resolved_by: int) -> None:
        self.status = status
        self.resolved_at = now_utc()
        self.resolved_by = resolved_by

    def _register_created(self) -> None:
        self.register_event(
            CreatedChatJoinRequestEvent(
                chat_id=str(self.chat_id),
                user_id=self.user_id,
                invite_link_id=str(self.invite_link_id) if self.invite_link_id else None,
                requested_at=self.requested_at.isoformat(),
            )
        )
