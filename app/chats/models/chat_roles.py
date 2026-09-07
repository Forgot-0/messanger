from enum import IntEnum
from typing import Self

from sqlalchemy import JSON, BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.chats.exceptions import TooLongChatRoleNameError
from app.core.db.base_model import BaseModel


class ChatRoleId(IntEnum):
    OWNER = 1
    ADMIN = 2
    EDITOR = 3
    DIRECT_MEMBER = 4
    MEMBER = 5
    VIEWER = 6


CHAT_ROLE_LEVELS: dict[ChatRoleId, int] = {
    ChatRoleId.OWNER: 100,
    ChatRoleId.ADMIN: 90,
    ChatRoleId.EDITOR: 80,
    ChatRoleId.DIRECT_MEMBER: 70,
    ChatRoleId.MEMBER: 10,
    ChatRoleId.VIEWER: 1,
}


def chat_role_level(role_id: int) -> int | None:
    try:
        return CHAT_ROLE_LEVELS[ChatRoleId(role_id)]
    except ValueError:
        return None


class ChatRole(BaseModel):
    __tablename__ = "chat_roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    name: Mapped[str] = mapped_column(
        String(32),
        nullable=False, index=True
    )
    level: Mapped[int] = mapped_column(Integer, default=1)
    permissions: Mapped[dict[str, bool]] = mapped_column(JSON, server_default="{}")

    @classmethod
    def create(cls, name: str, level: int, permissions: dict[str, bool]) -> Self:
        instance = cls(
            name=name,
            level=level,
            permissions=permissions
        )
        instance._validate_role_name(name)
        return instance

    def has_permission(self, permission_key: str) -> bool:
        return bool(self.permissions.get(permission_key))

    def _validate_role_name(self, name: str) -> None:
        if len(name) > 32:
            raise TooLongChatRoleNameError(role_name=name)

