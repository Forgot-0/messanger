from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel, DateMixin


class PlatformEnum(StrEnum):
    ios = "IOS"
    web = "WEB"
    android = "ANDROID"


class UserDeviceToken(BaseModel, DateMixin):
    __tablename__ = "user_device_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    token: Mapped[str] = mapped_column(
        String(512), nullable=False,
        comment="FCM registration token или APNs device token",
    )
    platform: Mapped[PlatformEnum] = mapped_column(
        Enum(PlatformEnum), nullable=False,
        comment="android | ios | web",
    )
    device_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="Читаемое имя: 'iPhone 15 Pro', 'Chrome on Windows'",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("user_id", "token", name="uq_device_token"),
        Index("ix_device_tokens_user_active", "user_id", "is_active"),
    )

    @classmethod
    def create(
        cls, user_id: int, token: str, platform: PlatformEnum,
        device_name: str,
    ) -> UserDeviceToken:
        instance = cls(
            user_id=user_id,
            token=token,
            platform=platform,
            device_name=device_name
        )
        return instance

