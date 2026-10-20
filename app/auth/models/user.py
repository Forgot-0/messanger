from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.config import auth_config
from app.auth.exceptions import InvalidUsernameError, NotFoundPermissionsError, NotFoundRoleError
from app.auth.models.oauth import OAuthAccount
from app.auth.models.session import Session
from app.core.db.base_model import BaseModel, DateMixin, SoftDeleteMixin
from app.core.events.event import BaseEvent

if TYPE_CHECKING:
    from app.auth.models.permission import Permission
    from app.auth.models.role import Role


_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*[A-Za-z0-9]$")


@dataclass(frozen=True)
class CreatedUserEvent(BaseEvent):
    email: str
    username: str

    __event_name__: str = "auth.user.created"

    def get_aggregate_id(self) -> str:
        return str(self.username)


@dataclass(frozen=True)
class VerifiedUserEvent(BaseEvent):
    user_id: int
    username: str
    email: str

    __event_name__: str = "auth.user.verified"

    def get_aggregate_id(self) -> str:
        return str(self.user_id)


@dataclass(frozen=True)
class DeletedUserEvent(BaseEvent):
    user_id: int
    username: str
    email: str

    __event_name__: str = "auth.user.deleted"

    def get_aggregate_id(self) -> str:
        return str(self.user_id)


@dataclass(frozen=True)
class ChangedUsernameEvent(BaseEvent):
    user_id: int
    old_username: str
    username: str

    __event_name__: str = "auth.user.username_changed"

    def get_aggregate_id(self) -> str:
        return str(self.user_id)


class UserPermissions(BaseModel):
    __tablename__ = "user_permissions"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="cascade", onupdate="cascade"),
        primary_key=True,
    )
    permission_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("permissions.id", ondelete="cascade", onupdate="cascade"),
        primary_key=True,
    )


class User(BaseModel, DateMixin, SoftDeleteMixin):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_username_lower", text("lower(username)"), unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="noload"
    )
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    roles: Mapped[set[Role]] = relationship(
        secondary="user_roles",
        back_populates="users",
    )

    permissions: Mapped[set[Permission]] = relationship(
        "Permission", secondary="user_permissions", back_populates="users"
    )

    @classmethod
    def create(
        cls, email: str, username: str, password_hash: str | None,
        roles: set[Role], is_verified: bool=False
    ) -> User:
        user = User(
            email=email,
            username=username,
            password_hash=password_hash,
            roles=roles,
            is_active=True,
            is_verified=is_verified,
            permissions=set(),
            sessions=[],
        )

        user.register_event(
            CreatedUserEvent(
                email=email,
                username=username
            )
        )
        return user

    @classmethod
    def create_oauth(cls, email: str, username: str, roles: set[Role]) -> User:
        return User.create(
            email, username=username, password_hash=None,
            roles=roles, is_verified=True
        )

    def delete(self) -> None:
        self.soft_delete()
        self.register_event(
            DeletedUserEvent(
                user_id=self.id,
                username=self.username,
                email=self.email
            )
        )

    def change_username(self, username: str) -> None:
        username = self.validate_username(username)
        if username == self.username:
            return

        old_username = self.username
        self.username = username
        self.register_event(
            ChangedUsernameEvent(
                user_id=self.id,
                old_username=old_username,
                username=username,
            )
        )

    @staticmethod
    def validate_username(username: str) -> str:
        cleaned = username.strip().removeprefix("@")

        if not (
            auth_config.USERNAME_MIN_LENGTH
            <= len(cleaned)
            <= auth_config.USERNAME_MAX_LENGTH
        ):
            raise InvalidUsernameError(username=username, reason="length")

        if not _USERNAME_RE.fullmatch(cleaned):
            raise InvalidUsernameError(username=username, reason="format")

        if User.is_reserved_username(cleaned):
            raise InvalidUsernameError(username=username, reason="reserved")

        return cleaned

    @staticmethod
    def is_reserved_username(username: str) -> bool:
        return username.strip().lower() in auth_config.USERNAME_RESERVED

    def add_role(self, role: Role) -> None:
        self.roles.add(role)

    def delete_role(self, role: Role) -> None:
        if role not in self.roles:
            raise NotFoundRoleError(name=role.name)

        self.roles.remove(role)

    def add_permission(self, permission: Permission) -> None:
        self.permissions.add(permission)

    def delete_permission(self, permission: Permission) -> None:
        if permission not in self.permissions:
            raise NotFoundPermissionsError(missing={permission.name, })

        self.permissions.remove(permission)

    def password_reset(self, password_hash: str) -> None:
        self.password_hash = password_hash

    def verify(self) -> None:
        self.is_verified = True
        self.register_event(
            VerifiedUserEvent(
                user_id=self.id,
                username=self.username,
                email=self.email
            )
        )

    def has_permission(self, permission: Permission) -> bool:
        return any(role.has_permission(permission) for role in self.roles) or permission in self.permissions

