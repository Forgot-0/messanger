from dataclasses import dataclass, field
from datetime import datetime
from typing import Self
from uuid import UUID

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.chats.config import chat_config
from app.core.db.base_model import BaseModel, DateMixin
from app.core.events.event import BaseEvent
from app.core.utils import now_utc


@dataclass(frozen=True)
class ReactionGroupSnapshot:
    emoji: str
    count: int

@dataclass(frozen=True)
class ReactionUpdatedEvent(BaseEvent):
    message_id: str
    chat_id: str
    actor_id: int
    action: str
    groups: list[ReactionGroupSnapshot] = field(default_factory=list)
    recent_by_emoji: dict[str, list[int]] = field(default_factory=dict)

    __event_name__ = "chats.message.reaction_updated"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


class MessageReaction(BaseModel, DateMixin):
    __tablename__ = "message_reactions"

    message_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    emoji: Mapped[str] = mapped_column(
        String(chat_config.MAX_REACTION_LENGTH), primary_key=True
    )

    chat_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_message_reactions_recent",
            "message_id",
            "emoji",
            "created_at",
        ),
        Index("ix_message_reactions_chat_message", "chat_id", "message_id"),
    )

    @classmethod
    def create(cls, chat_id: UUID, message_id: UUID, user_id: int, emoji: str) -> Self:
        return cls(
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            emoji=emoji,
        )


class MessageReactionCounter(BaseModel):
    __tablename__ = "message_reaction_counters"

    message_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    emoji: Mapped[str] = mapped_column(
        String(chat_config.MAX_REACTION_LENGTH), primary_key=True
    )

    chat_id: Mapped[UUID] = mapped_column(SAUUID(as_uuid=True), nullable=False)
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    first_reacted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc
    )
    last_reacted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc
    )

    __table_args__ = (
        Index("ix_message_reaction_counters_chat_message", "chat_id", "message_id"),
    )
