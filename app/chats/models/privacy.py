from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel


class ChatUserContact(BaseModel):
    __tablename__ = "chat_user_contacts"

    owner_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    contact_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatUserPrivacyException(BaseModel):
    __tablename__ = "chat_user_privacy_exceptions"

    owner_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    rule: Mapped[str] = mapped_column(String(16), primary_key=True)
    target_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    allow: Mapped[bool] = mapped_column(Boolean, nullable=False)
