from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel
from app.core.utils import now_utc
from app.profiles.models.profile import AvatarMap


class ProfilePhoto(BaseModel):
    __tablename__ = "profile_photos"
    __table_args__ = (
        Index("ix_profile_photos_user_order", "user_id", text("set_main_at DESC"), text("id DESC")),
    )

    id: Mapped[UUID] = mapped_column(SAUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    avatars: Mapped[AvatarMap] = mapped_column(JSONB, nullable=False)
    set_main_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @classmethod
    def create(cls, photo_id: UUID, user_id: int, avatars: AvatarMap) -> ProfilePhoto:
        now = now_utc()
        return cls(
            id=photo_id,
            user_id=user_id,
            avatars=avatars,
            set_main_at=now,
            created_at=now,
        )

    def make_main(self) -> None:
        self.set_main_at = now_utc()
