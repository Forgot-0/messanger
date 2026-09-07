from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.messages.delete import DeleteMessageCommand, DeleteMessageCommandHandler
from app.chats.exceptions import AccessDeniedChatError, NotFoundMessageError
from app.chats.models.chat import Chat
from app.chats.repositories.message import MessageRepository
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestDeleteMessageCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> DeleteMessageCommandHandler:
        return await request_container.get(DeleteMessageCommandHandler)

    async def test_author_deletes_own_message(
        self,
        handler: DeleteMessageCommandHandler,
        message_repository: MessageRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        msg = await create_message(group_chat, user_jwt, "Delete")

        await handler.handle(
            DeleteMessageCommand(
                chat_id=group_chat.id,
                message_id=msg.id,
                user_jwt_data=user_jwt,
            )
        )

        deleted = await message_repository.get_by_id(msg.id)
        assert deleted is None

    async def test_owner_moderates_member_message(
        self,
        handler: DeleteMessageCommandHandler,
        message_repository: MessageRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        msg = await create_message(group_chat, make_user_jwt(id="2"), "Delete")
        await handler.handle(
            DeleteMessageCommand(
                chat_id=group_chat.id,
                message_id=msg.id,
                user_jwt_data=user_jwt,
            )
        )

        deleted = await message_repository.get_by_id(msg.id)
        assert deleted is None

    async def test_member_cannot_delete_others_message(
        self,
        handler: DeleteMessageCommandHandler,
        group_chat: Chat,
        create_message,
        make_user_jwt,
    ) -> None:
        msg = await create_message(group_chat, make_user_jwt(id="2"), "Delete")

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                DeleteMessageCommand(
                    chat_id=group_chat.id,
                    message_id=msg.id,
                    user_jwt_data=make_user_jwt(id="3"),
                )
            )

    async def test_delete_nonexistent_message_raises(
        self,
        handler: DeleteMessageCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundMessageError):
            await handler.handle(
                DeleteMessageCommand(
                    chat_id=group_chat.id,
                    message_id=uuid4(),
                    user_jwt_data=user_jwt,
                )
            )
