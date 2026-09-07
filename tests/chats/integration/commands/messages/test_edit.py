from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.messages.modify import EditMessageCommand, EditMessageCommandHandler
from app.chats.exceptions import AccessDeniedChatError, NotFoundMessageError
from app.chats.models.chat import Chat
from app.chats.repositories.message import MessageRepository
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestEditMessageCommand:
    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> EditMessageCommandHandler:
        return await request_container.get(EditMessageCommandHandler)

    async def test_author_edits_own_message(
        self,
        handler: EditMessageCommandHandler,
        message_repository: MessageRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        original = await create_message(group_chat, user_jwt, "Original")
        await handler.handle(
            EditMessageCommand(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                message_id=original.id,
                new_content="Edited content",
            )
        )

        msg = await message_repository.get_by_id(original.id)
        assert msg is not None
        assert msg.content == "Edited content"
        assert msg.is_edited is True

    async def test_non_author_cannot_edit(
        self,
        handler: EditMessageCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        msg = await create_message(group_chat, make_user_jwt(id="2"), "Original")

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                EditMessageCommand(
                    user_jwt_data=user_jwt,
                    chat_id=group_chat.id,
                    message_id=msg.id,
                    new_content="Hijacked",
                )
            )

    async def test_edit_nonexistent_message_raises(
        self,
        handler: EditMessageCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundMessageError):
            await handler.handle(
                EditMessageCommand(
                    user_jwt_data=user_jwt,
                    chat_id=group_chat.id,
                    message_id=uuid4(),
                    new_content="X",
                )
            )

    async def test_edit_message_from_different_chat_raises(
        self,
        handler: EditMessageCommandHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData
    ) -> None:
        chat_a = await create_group_chat([2, 3])
        chat_b = await create_group_chat([2, 3])

        msg_in_a = await create_message(chat_a, user_jwt, "In A")

        with pytest.raises(NotFoundMessageError):
            await handler.handle(
                EditMessageCommand(
                    user_jwt_data=user_jwt,
                    chat_id=chat_b.id,
                    message_id=msg_in_a.id,
                    new_content="Bad edit",
                )
            )
