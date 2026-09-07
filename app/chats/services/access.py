from dataclasses import dataclass
from uuid import UUID

from app.chats.exceptions import AccessDeniedChatError, InvalidChatRoleError
from app.chats.models.chat import Chat
from app.chats.models.chat_members import ChatMember
from app.chats.models.chat_roles import chat_role_level
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.rbac import RBACManagerInterface


@dataclass
class ChatAccessService:
    rbac_manager: RBACManagerInterface

    def _has_global_chat_admin(self, user_jwt_data: UserJWTData) -> bool:
        return self.rbac_manager.check_permission(user_jwt_data, {"chat:update"})

    async def has_permissions(
        self,
        user_jwt_data: UserJWTData,
        member: ChatMember | None,
        must_permissions: set[str]
    ) -> bool:
        if self._has_global_chat_admin(user_jwt_data):
            return True

        if member is None or member.is_banned:
            return False

        if "message:send" in must_permissions and member.is_muted:
            return False

        member_permissions = member.effective_permissions()
        return all(member_permissions.get(perm, False) for perm in must_permissions)

    async def can_send_message(
        self,
        user_jwt_data: UserJWTData,
        chat: Chat,
        member: ChatMember | None,
    ) -> bool:
        if self._has_global_chat_admin(user_jwt_data):
            return True

        if member is None or member.is_banned or member.is_muted:
            return False

        member_permissions = member.effective_permissions()
        if not member_permissions.get("message:send", False):
            return False

        if chat.admin_only and not (
            member.is_staff or member_permissions.get("message:send_admin_only", False)
        ):
            return False

        if (
            chat.permissions
            and chat.permissions.get("message:send") is False
            and not member.is_staff
        ):
            return False

        return True

    def can_bypass_slow_mode(self, member: ChatMember | None) -> bool:
        if member is None or member.is_banned:
            return False
        return member.can_bypass_slow_mode()

    def ensure_can_assign_role(
        self,
        user_jwt_data: UserJWTData,
        requester: ChatMember | None,
        chat_id: UUID,
        role_id: int,
    ) -> None:
        role_level = chat_role_level(role_id)
        if role_level is None:
            raise InvalidChatRoleError(role_id=role_id)

        if self._has_global_chat_admin(user_jwt_data):
            return

        if requester is None or requester.is_banned or role_level >= requester.role.level:
            raise AccessDeniedChatError(
                chat_id=str(chat_id), requester_id=int(user_jwt_data.id)
            )

    async def update_member(
        self,
        user_jwt_data: UserJWTData,
        requester: ChatMember | None,
        target: ChatMember,
        must_permissions: set[str]
    ) -> bool:
        if self._has_global_chat_admin(user_jwt_data):
            return True

        if requester is None or requester.is_banned or requester.id == target.id:
            return False

        member_permissions = requester.effective_permissions()
        for perm in must_permissions:
            if not member_permissions.get(perm, False):
                return False

        return requester.role.level >= target.role.level
