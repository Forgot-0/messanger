from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel, DateMixin


class ReadReceipt(BaseModel, DateMixin):
    __tablename__ = "read_receipts"

    chat_id: Mapped[UUID] = mapped_column(
        SAUUID, ForeignKey("chats.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_read_message_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
