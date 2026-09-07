from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self
from uuid import UUID

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    ColumnElement,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    and_,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.chats.config import chat_config
from app.chats.models.chat_roles import ChatRole, ChatRoleId
from app.chats.models.profile import ChatUserProfile
from app.core.db.base_model import BaseModel, DateMixin
from app.core.utils import now_utc

if TYPE_CHECKING:
    from app.chats.models.chat import Chat

PERMANENT_UNTIL = datetime(9999, 12, 31, tzinfo=UTC)


class ChatMember(BaseModel, DateMixin):
    __tablename__ = "chat_members"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    chat_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat_roles.id", ondelete="CASCADE"), index=True
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    banned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)

    permissions_overrides: Mapped[dict[str, bool]] = mapped_column(JSONB, server_default="{}")

    chat: Mapped[Chat] = relationship("Chat", back_populates="members", lazy="noload")
    role: Mapped[ChatRole] = relationship("ChatRole")
    bans: Mapped[list[ChatMemberBan]] = relationship("ChatMemberBan", back_populates="member", lazy="noload")

    profile: Mapped[ChatUserProfile | None] = relationship(
        ChatUserProfile,
        foreign_keys=[user_id],
        primaryjoin="ChatMember.user_id == ChatUserProfile.user_id",
        lazy="noload",
        viewonly=True,
    )

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_chat_member"),
        Index("ix_chat_members_user_chat", "user_id", "chat_id"),
        Index("ix_chat_members_chat_active_user", "chat_id", "user_id"),
        Index("ix_chat_members_chat_role_user", "chat_id", "role_id", "user_id"),
    )


    @classmethod
    def create(cls, chat_id: UUID, user_id: int, role_id: int) -> Self:
        return cls(chat_id=chat_id, user_id=user_id, role_id=role_id)

    def ban(
        self,
        banned_by: int,
        reason: str | None = None,
        banned_until: datetime | None = None,
    ) -> None:
        if banned_until is None:
            self.banned_until = PERMANENT_UNTIL

        elif banned_until <= now_utc():
            self.banned_until = None

        else:
            self.banned_until = banned_until

        self.bans.append(
            ChatMemberBan(
                member_id=self.id,
                banned_by_user_id=banned_by,
                reason=reason,
                banned_at=now_utc(),
                banned_until=self.banned_until,
            )
        )

    def mute(self, muted_until: datetime | None = None) -> None:
        if muted_until is None:
            self.muted_until = PERMANENT_UNTIL

        elif muted_until <= now_utc():
            self.muted_until = None

        else:
            self.muted_until = muted_until

    def effective_permissions(self) -> dict[str, bool]:
        perms = self.role.permissions.copy()
        if self.permissions_overrides:
            perms.update(self.permissions_overrides)
        return perms

    def has_permission(self, permission_key: str) -> bool:
        if self.permissions_overrides and permission_key in self.permissions_overrides:
            return bool(self.permissions_overrides[permission_key])
        return self.role.has_permission(permission_key)

    @property
    def role_name(self) -> str:
        return self.role.name

    @hybrid_property
    def is_banned(self) -> bool:
        return self.banned_until is not None and self.banned_until > now_utc()

    @is_banned.inplace.expression
    @classmethod
    def _is_banned_expression(cls) -> ColumnElement[bool]:
        return and_(cls.banned_until.is_not(None), cls.banned_until > now_utc())

    @hybrid_property
    def is_muted(self) -> bool:
        return self.muted_until is not None and self.muted_until > now_utc()

    @is_muted.inplace.expression
    @classmethod
    def _is_muted_expression(cls) -> ColumnElement[bool]:
        return and_(cls.muted_until.is_not(None), cls.muted_until > now_utc())

    @classmethod
    def active_criteria(cls) -> ColumnElement[bool]:
        return ~cls.is_banned

    @property
    def is_staff(self) -> bool:
        return self.role.level >= chat_config.CHAT_STAFF_MIN_ROLE_LEVEL

    @property
    def is_editor_or_above(self) -> bool:
        return self.role.level >= chat_config.CHAT_EDITOR_MIN_ROLE_LEVEL

    @property
    def is_channel_subscriber(self) -> bool:
        return self.role_id == ChatRoleId.VIEWER

    @property
    def is_channel_staff(self) -> bool:
        return self.role_id in {
            ChatRoleId.OWNER, ChatRoleId.ADMIN, ChatRoleId.EDITOR
        } or self.is_editor_or_above

    def can_bypass_slow_mode(self) -> bool:
        return self.is_staff or self.has_permission("slowmode:bypass")



class ChatMemberBan(BaseModel):
    __tablename__ = "chat_member_bans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat_members.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    banned_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    banned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    banned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    member: Mapped[ChatMember] = relationship("ChatMember", back_populates="bans")

    __table_args__ = (
        Index("ix_chat_member_bans_member_banned_at", "member_id", "banned_at"),
    )
