from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum as SAEnum,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel, DateMixin


class NotificationType(StrEnum):
    SYSTEM = "system"
    PROJECT = "project"
    CHAT = "chat"


class Notification(BaseModel, DateMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    type: Mapped[NotificationType] = mapped_column(SAEnum(NotificationType), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_unread", "user_id", "is_read"),
    )

    @classmethod
    def create(
        cls, user_id: int, type: NotificationType,
        title: str, message: str | None, payload: dict
    ) -> Notification:
        instance = cls(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            payload=payload,
        )
        return instance

