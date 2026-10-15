from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel


class ChatUserBlock(BaseModel):
    __tablename__ = "chat_user_blocks"

    owner_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    target_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
