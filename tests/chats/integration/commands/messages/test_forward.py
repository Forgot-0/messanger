from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.messages.forward import ForwardMessageCommand, ForwardMessageCommandHandler
from app.chats.exceptions import NotChatMemberError, NotFoundMessageError
from app.chats.models.message import MessageType
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestForwardMessageCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> ForwardMessageCommandHandler:
        return await request_container.get(ForwardMessageCommandHandler)

    async def test_forward_message_to_another_chat(
        self,
        handler: ForwardMessageCommandHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData
    ) -> None:
        src = await create_group_chat([2, 3])
        tgt = await create_group_chat([2, 3])

        original = await create_message(src, user_jwt, "In A")

        fwd = await handler.handle(
            ForwardMessageCommand(
                user_jwt_data=user_jwt,
                source_chat_id=src.id,
                source_message_id=original.id,
                target_chat_id=tgt.id,
            )
        )

        assert fwd.type == MessageType.FORWARD
        assert fwd.forwarded_from_message_id == original.id
        assert fwd.chat_id == tgt.id

    async def test_forward_carries_original_author(
        self,
        handler: ForwardMessageCommandHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt
    ) -> None:
        src = await create_group_chat([2, 3])
        tgt = await create_group_chat([2, 3])

        original = await create_message(src, make_user_jwt(id="2"), "Original")

        fwd = await handler.handle(
            ForwardMessageCommand(
                user_jwt_data=user_jwt,
                source_chat_id=src.id,
                source_message_id=original.id,
                target_chat_id=tgt.id,
            )
        )

        assert fwd.forwarded_from_author_id == 2

    async def test_forward_nonexistent_source_raises(
        self,
        handler: ForwardMessageCommandHandler,
        create_group_chat,
        user_jwt: UserJWTData,
    ) -> None:
        src = await create_group_chat([2, 3])
        tgt = await create_group_chat([2, 3])

        with pytest.raises(NotFoundMessageError):
            await handler.handle(
                ForwardMessageCommand(
                    user_jwt_data=user_jwt,
                    source_chat_id=src.id,
                    source_message_id=uuid4(),
                    target_chat_id=tgt.id,
                )
            )

    async def test_outsider_cannot_forward_from_private_chat(
        self,
        handler: ForwardMessageCommandHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt
    ) -> None:
        src = await create_group_chat([2])
        tgt = await create_group_chat([3])

        original = await create_message(src, user_jwt, "Test")

        with pytest.raises(NotChatMemberError):
            await handler.handle(
                ForwardMessageCommand(
                    user_jwt_data=make_user_jwt(id="3"),
                    source_chat_id=src.id,
                    source_message_id=original.id,
                    target_chat_id=tgt.id,
                )
            )
