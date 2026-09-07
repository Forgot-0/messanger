from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.messages.send import SendMessageCommand, SendMessageCommandHandler
from app.chats.exceptions import AccessDeniedChatError, NotFoundChatError, SlowModeLimitError
from app.chats.models.message import MessageType
from app.chats.repositories.message import MessageRepository
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestSendMessageCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> SendMessageCommandHandler:
        return await request_container.get(SendMessageCommandHandler)

    async def test_send_text_message_persists_and_fires_event(
        self,
        handler: SendMessageCommandHandler,
        message_repository: MessageRepository,
        create_group_chat,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_group_chat([2, 3])

        dto = await handler.handle(
            SendMessageCommand(
                chat_id=chat.id,
                content="Hello world",
                user_jwt_data=user_jwt,
            )
        )

        msg = await message_repository.get_by_id(dto.id)
        assert msg is not None
        assert msg.content == "Hello world"
        assert msg.seq == 1
        assert msg.author_id == int(user_jwt.id)

    async def test_seq_increments_per_message(
        self,
        handler: SendMessageCommandHandler,
        create_group_chat,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_group_chat([2, 3])

        m1 = await handler.handle(
            SendMessageCommand(chat_id=chat.id, content="First", user_jwt_data=user_jwt)
        )

        m2 = await handler.handle(
            SendMessageCommand(chat_id=chat.id, content="Second", user_jwt_data=user_jwt)
        )

        assert m2.seq == m1.seq + 1

    async def test_send_reply_references_parent(
        self,
        handler: SendMessageCommandHandler,
        create_group_chat,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_group_chat([2, 3])
        parent = await handler.handle(
            SendMessageCommand(chat_id=chat.id, content="Parent", user_jwt_data=user_jwt)
        )

        reply = await handler.handle(
            SendMessageCommand(
                chat_id=chat.id,
                content="Reply",
                reply_to_id=parent.id,
                message_type=MessageType.REPLY,
                user_jwt_data=user_jwt,
            )
        )

        assert reply.reply_to_id == parent.id

    async def test_outsider_cannot_send(
        self,
        handler: SendMessageCommandHandler,
        create_group_chat,
        make_user_jwt,
    ) -> None:
        chat = await create_group_chat([2, 3])

        with pytest.raises(NotFoundChatError):
            await handler.handle(
                SendMessageCommand(chat_id=chat.id, content="Hack", user_jwt_data=make_user_jwt(id="99"))
            )

    async def test_send_to_nonexistent_chat_raises(
        self,
        handler: SendMessageCommandHandler,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundChatError):
            await handler.handle(
                SendMessageCommand(chat_id=uuid4(), content="X", user_jwt_data=user_jwt)
            )

    async def test_slow_mode_blocks_rapid_second_message(
        self,
        handler: SendMessageCommandHandler,
        create_group_chat,
        make_user_jwt
    ) -> None:
        chat = await create_group_chat([2, 3], 3600)

        await handler.handle(
            SendMessageCommand(chat_id=chat.id, content="First", user_jwt_data=make_user_jwt(id="2"))
        )

        with pytest.raises(SlowModeLimitError):
            await handler.handle(
                SendMessageCommand(chat_id=chat.id, content="Too fast", user_jwt_data=make_user_jwt(id="2"))
            )

    async def test_owner_bypasses_slow_mode(
        self,
        handler: SendMessageCommandHandler,
        create_group_chat,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_group_chat([2, 3], 3600)

        await handler.handle(
            SendMessageCommand(chat_id=chat.id, content="M1", user_jwt_data=user_jwt)
        )

        dto2 = await handler.handle(
            SendMessageCommand(chat_id=chat.id, content="M2", user_jwt_data=user_jwt)
        )
        assert dto2.seq == 2

    async def test_html_content_is_stored_verbatim(
        self,
        handler: SendMessageCommandHandler,
        create_group_chat,
        user_jwt: UserJWTData,
    ) -> None:
        chat = await create_group_chat([2, 3], 3600)
        dto = await handler.handle(
            SendMessageCommand(
                chat_id=chat.id,
                content='<script>alert("xss")</script>',
                user_jwt_data=user_jwt,
            )
        )
        assert dto.content == '<script>alert("xss")</script>'

    async def test_admin_only_chat_blocks_regular_member(
        self,
        handler: SendMessageCommandHandler,
        create_group_chat,
        make_user_jwt
    ) -> None:
        chat = await create_group_chat([2, 3], 0, admin_only=True)

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                SendMessageCommand(chat_id=chat.id, content="Blocked", user_jwt_data=make_user_jwt(id="2"))
            )
