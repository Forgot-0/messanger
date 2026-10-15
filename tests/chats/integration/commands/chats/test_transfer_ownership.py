import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.chats.leave import LeaveChatCommand, LeaveChatCommandHandler
from app.chats.commands.chats.transfer_ownership import (
    TransferChatOwnershipCommand,
    TransferChatOwnershipCommandHandler,
)
from app.chats.exceptions import (
    AccessDeniedChatError,
    InvalidOwnershipTransferError,
    NotChatMemberError,
)
from app.chats.models.chat import Chat, TransferredChatOwnershipEvent
from app.chats.models.chat_roles import ChatRoleId
from app.chats.repositories.chat import ChatRepository
from app.core.services.auth.dto import UserJWTData
from tests.mocks import RecordingEventBus


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestTransferChatOwnership:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> TransferChatOwnershipCommandHandler:
        return await request_container.get(TransferChatOwnershipCommandHandler)

    async def test_owner_transfers_ownership(
        self,
        handler: TransferChatOwnershipCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        await handler.handle(TransferChatOwnershipCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, new_owner_id=2,
        ))

        chat = await chat_repository.get_by_id(group_chat.id)
        assert chat is not None
        assert chat.created_by == 2

        new_owner = await chat_repository.get_member_chat(group_chat.id, 2)
        old_owner = await chat_repository.get_member_chat(group_chat.id, 1)
        assert new_owner is not None and new_owner.role_id == ChatRoleId.OWNER
        assert old_owner is not None and old_owner.role_id == ChatRoleId.ADMIN

        event = mock_event_bus.one_of_type(TransferredChatOwnershipEvent)
        assert (event.previous_owner_id, event.new_owner_id, event.requester_id) == (1, 2, 1)

    async def test_previous_owner_can_leave_after_transfer(
        self,
        handler: TransferChatOwnershipCommandHandler,
        request_container: AsyncContainer,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(TransferChatOwnershipCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, new_owner_id=2,
        ))

        leave = await request_container.get(LeaveChatCommandHandler)
        await leave.handle(LeaveChatCommand(chat_id=group_chat.id, user_jwt_data=user_jwt))

        assert await chat_repository.get_member_chat(group_chat.id, 1) is None

    async def test_admin_cannot_transfer(
        self,
        handler: TransferChatOwnershipCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        db_session: AsyncSession,
        make_user_jwt,
    ) -> None:
        admin = await chat_repository.get_member_chat(group_chat.id, 2)
        assert admin is not None
        admin.role_id = ChatRoleId.ADMIN
        await db_session.commit()

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(TransferChatOwnershipCommand(
                user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id, new_owner_id=3,
            ))

    async def test_transfer_to_non_member(
        self,
        handler: TransferChatOwnershipCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotChatMemberError):
            await handler.handle(TransferChatOwnershipCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, new_owner_id=404,
            ))

    async def test_transfer_to_banned_member(
        self,
        handler: TransferChatOwnershipCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        target = await chat_repository.get_member_chat(group_chat.id, 3)
        assert target is not None
        target.ban(banned_by=int(user_jwt.id))
        await db_session.commit()

        with pytest.raises(InvalidOwnershipTransferError):
            await handler.handle(TransferChatOwnershipCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, new_owner_id=3,
            ))

    async def test_direct_chat_has_no_owner_to_transfer(
        self,
        handler: TransferChatOwnershipCommandHandler,
        direct_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(InvalidOwnershipTransferError):
            await handler.handle(TransferChatOwnershipCommand(
                user_jwt_data=user_jwt, chat_id=direct_chat.id, new_owner_id=2,
            ))
