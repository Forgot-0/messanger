from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.chats.delete import DeleteChatCommand, DeleteChatCommandHandler
from app.chats.exceptions import AccessDeniedChatError, NotFoundChatError
from app.chats.models.chat import Chat
from app.chats.repositories.chat import ChatRepository
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestDeleteChatCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> DeleteChatCommandHandler:
        return await request_container.get(DeleteChatCommandHandler)

    async def test_owner_can_delete_group(
        self,
        handler: DeleteChatCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            DeleteChatCommand(chat_id=group_chat.id, user_jwt_data=user_jwt)
        )

        group = await chat_repository.get_by_id(chat_id=group_chat.id)
        assert group is None

    async def test_regular_member_cannot_delete(
        self,
        handler: DeleteChatCommandHandler,
        group_chat: Chat,
        make_user_jwt
    ) -> None:

        member = make_user_jwt(id="2")
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                DeleteChatCommand(chat_id=group_chat.id, user_jwt_data=member)
            )

    async def test_delete_nonexistent_chat_raises(
        self,
        handler: DeleteChatCommandHandler,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundChatError):
            await handler.handle(
                DeleteChatCommand(chat_id=uuid4(), user_jwt_data=user_jwt)
            )
