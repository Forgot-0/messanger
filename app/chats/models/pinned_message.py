from datetime import datetime
from typing import Self
from uuid import UUID

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel
from app.core.utils import now_utc


class ChatPinnedMessage(BaseModel):
    __tablename__ = "chat_pinned_messages"

    chat_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    message_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    message_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pinned_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pinned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_chat_pinned_messages_chat_seq", "chat_id", "message_seq"),
    )

    @classmethod
    def create(cls, chat_id: UUID, message_id: UUID, message_seq: int, pinned_by: int) -> Self:
        return cls(
            chat_id=chat_id,
            message_id=message_id,
            message_seq=message_seq,
            pinned_by=pinned_by,
            pinned_at=now_utc(),
        )
