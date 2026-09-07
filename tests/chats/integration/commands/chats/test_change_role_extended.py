import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.chats.add_member import AddMemberCommand, AddMemberCommandHandler
from app.chats.commands.chats.change_role import ChangeMemberRoleCommand, ChangeMemberRoleCommandHandler
from app.chats.exceptions import AccessDeniedChatError, InvalidChatRoleError, NotChatMemberError
from app.chats.models.chat import Chat
from app.chats.models.permission import ChatRolesEnum
from app.chats.repositories.chat import ChatRepository
from app.core.services.auth.dto import UserJWTData

OWNER_ID  = ChatRolesEnum.OWNER.value.id
ADMIN_ID  = ChatRolesEnum.ADMIN.value.id
EDITOR_ID = ChatRolesEnum.EDITOR.value.id
MEMBER_ID = ChatRolesEnum.MEMBER.value.id
VIEWER_ID = ChatRolesEnum.VIEWER.value.id


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChangeMemberRoleDowngrade:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> ChangeMemberRoleCommandHandler:
        return await request_container.get(ChangeMemberRoleCommandHandler)

    async def _get_role_id(self, chat_repository: ChatRepository, chat: Chat, user_id: int) -> int:
        member = await chat_repository.get_member_chat(chat.id, user_id)
        assert member is not None
        return member.role_id

    async def test_owner_promotes_member_to_admin(
        self,
        handler: ChangeMemberRoleCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            ChangeMemberRoleCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                role_id=ADMIN_ID,
            )
        )
        assert await self._get_role_id(chat_repository, group_chat, 2) == ADMIN_ID

    async def test_owner_promotes_member_to_editor(
        self,
        handler: ChangeMemberRoleCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            ChangeMemberRoleCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                role_id=EDITOR_ID,
            )
        )
        assert await self._get_role_id(chat_repository, group_chat, 2) == EDITOR_ID

    async def test_owner_downgrades_admin_to_viewer(
        self,
        handler: ChangeMemberRoleCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        member.role_id = ADMIN_ID
        await db_session.commit()

        await handler.handle(
            ChangeMemberRoleCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                role_id=VIEWER_ID,
            )
        )

        assert await self._get_role_id(chat_repository, group_chat, 2) == VIEWER_ID

    async def test_owner_downgrades_member_to_viewer(
        self,
        handler: ChangeMemberRoleCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            ChangeMemberRoleCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                role_id=VIEWER_ID,
            )
        )
        role_id = await self._get_role_id(chat_repository, group_chat, 2)
        assert role_id == VIEWER_ID

    async def test_viewer_has_no_send_permission_after_downgrade(
        self,
        handler: ChangeMemberRoleCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            ChangeMemberRoleCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                role_id=VIEWER_ID,
            )
        )

        member = await chat_repository.get_member_chat(group_chat.id, 2, with_role=True)
        assert member is not None
        perms = member.effective_permissions()
        assert perms.get("message:send") is False

    async def test_viewer_retains_read_permission_after_downgrade(
        self,
        handler: ChangeMemberRoleCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            ChangeMemberRoleCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                role_id=VIEWER_ID,
            )
        )

        member = await chat_repository.get_member_chat(group_chat.id, 2, with_role=True)
        assert member is not None
        perms = member.effective_permissions()
        assert perms.get("message:read") is True

    async def test_viewer_loses_admin_permissions_after_downgrade(
        self,
        handler: ChangeMemberRoleCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        member.role_id = ADMIN_ID
        await db_session.commit()

        await handler.handle(
            ChangeMemberRoleCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                role_id=VIEWER_ID,
            )
        )

        refreshed = await chat_repository.get_member_chat(group_chat.id, 2, with_role=True)
        assert refreshed is not None
        perms = refreshed.effective_permissions()
        admin_only_perms = ["member:kick", "member:ban", "chat:update", "role:change"]
        for perm in admin_only_perms:
            assert perms.get(perm) is False

    async def test_member_cannot_downgrade_owner(
        self,
        handler: ChangeMemberRoleCommandHandler,
        group_chat: Chat,
        make_user_jwt,
        user_jwt: UserJWTData,
    ) -> None:
        member_jwt = make_user_jwt(id="2")
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                ChangeMemberRoleCommand(
                    user_jwt_data=member_jwt,
                    chat_id=group_chat.id,
                    target_user_id=int(user_jwt.id),
                    role_id=VIEWER_ID,
                )
            )

    async def test_admin_cannot_demote_owner(
        self,
        handler: ChangeMemberRoleCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
        db_session: AsyncSession,
    ) -> None:
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        member.role_id = ADMIN_ID
        await db_session.commit()

        admin_jwt = make_user_jwt(id="2")
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                ChangeMemberRoleCommand(
                    user_jwt_data=admin_jwt,
                    chat_id=group_chat.id,
                    target_user_id=int(user_jwt.id),
                    role_id=VIEWER_ID,
                )
            )

    async def test_change_role_nonexistent_member_raises(
        self,
        handler: ChangeMemberRoleCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotChatMemberError):
            await handler.handle(
                ChangeMemberRoleCommand(
                    user_jwt_data=user_jwt,
                    chat_id=group_chat.id,
                    target_user_id=9999,
                    role_id=VIEWER_ID,
                )
            )

    @pytest.mark.parametrize("role_id", [ADMIN_ID, EDITOR_ID, MEMBER_ID, VIEWER_ID])
    async def test_owner_can_assign_any_role_below_own(
        self,
        handler: ChangeMemberRoleCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        role_id: int,
    ) -> None:
        await handler.handle(
            ChangeMemberRoleCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                target_user_id=2,
                role_id=role_id,
            )
        )
        assert await self._get_role_id(chat_repository, group_chat, 2) == role_id


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestRoleAssignmentGuard:
    """Роль строго ниже собственной — иначе через смену роли уходит владение чатом."""

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> ChangeMemberRoleCommandHandler:
        return await request_container.get(ChangeMemberRoleCommandHandler)

    @pytest.fixture
    async def add_member_handler(self, request_container: AsyncContainer) -> AddMemberCommandHandler:
        return await request_container.get(AddMemberCommandHandler)

    async def _promote(
        self,
        db_session: AsyncSession,
        chat_repository: ChatRepository,
        chat: Chat,
        user_id: int,
        role_id: int,
    ) -> None:
        member = await chat_repository.get_member_chat(chat.id, user_id)
        assert member is not None
        member.role_id = role_id
        await db_session.commit()

    async def test_owner_cannot_hand_over_ownership_via_role_change(
        self,
        handler: ChangeMemberRoleCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                ChangeMemberRoleCommand(
                    user_jwt_data=user_jwt,
                    chat_id=group_chat.id,
                    target_user_id=2,
                    role_id=OWNER_ID,
                )
            )

    async def test_admin_cannot_promote_member_to_owner(
        self,
        handler: ChangeMemberRoleCommandHandler,
        chat_repository: ChatRepository,
        db_session: AsyncSession,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        await self._promote(db_session, chat_repository, group_chat, 2, ADMIN_ID)

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                ChangeMemberRoleCommand(
                    user_jwt_data=make_user_jwt(id="2"),
                    chat_id=group_chat.id,
                    target_user_id=3,
                    role_id=OWNER_ID,
                )
            )
        assert (await chat_repository.get_member_chat(group_chat.id, 3)).role_id == MEMBER_ID

    async def test_unknown_role_id_is_rejected(
        self,
        handler: ChangeMemberRoleCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(InvalidChatRoleError):
            await handler.handle(
                ChangeMemberRoleCommand(
                    user_jwt_data=user_jwt,
                    chat_id=group_chat.id,
                    target_user_id=2,
                    role_id=999,
                )
            )

    async def test_inviter_cannot_add_member_as_owner(
        self,
        add_member_handler: AddMemberCommandHandler,
        chat_repository: ChatRepository,
        db_session: AsyncSession,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        await self._promote(db_session, chat_repository, group_chat, 2, ADMIN_ID)

        with pytest.raises(AccessDeniedChatError):
            await add_member_handler.handle(
                AddMemberCommand(
                    user_jwt_data=make_user_jwt(id="2"),
                    chat_id=group_chat.id,
                    target_user_id=77_001,
                    role_id=OWNER_ID,
                )
            )
        assert await chat_repository.get_member_chat(group_chat.id, 77_001) is None
