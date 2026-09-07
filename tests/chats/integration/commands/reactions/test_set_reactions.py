from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.reactions.set_many import (
    SetReactionsCommand,
    SetReactionsCommandHandler,
)
from app.chats.exceptions import (
    InvalidReactionError,
    NotFoundChatError,
    NotFoundMessageError,
    TooManyReactionsError,
)
from app.chats.models.chat import Chat
from app.chats.repositories.reaction import MessageReactionRepository
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestSetReactionsCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> SetReactionsCommandHandler:
        return await request_container.get(SetReactionsCommandHandler)

    async def test_replaces_whole_set(
        self,
        handler: SetReactionsCommandHandler,
        reaction_repository: MessageReactionRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        await handler.handle(
            SetReactionsCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emojis=("👍", "🔥"),
                user_jwt_data=user_jwt,
            )
        )
        await handler.handle(
            SetReactionsCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emojis=("❤️",),
                user_jwt_data=user_jwt,
            )
        )

        emojis = await reaction_repository.list_user_emojis(message.id, int(user_jwt.id))
        assert emojis == ["❤️"]

    async def test_empty_list_clears_all(
        self,
        handler: SetReactionsCommandHandler,
        reaction_repository: MessageReactionRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")
        await handler.handle(
            SetReactionsCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emojis=("👍",),
                user_jwt_data=user_jwt,
            )
        )

        await handler.handle(
            SetReactionsCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emojis=(),
                user_jwt_data=user_jwt,
            )
        )

        assert await reaction_repository.get_current_groups(message.id) == []

    async def test_exceeds_per_user_limit_raises(
        self,
        handler: SetReactionsCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        with pytest.raises(TooManyReactionsError):
            await handler.handle(
                SetReactionsCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emojis=("👍", "🔥", "❤️", "🎉"),
                    user_jwt_data=user_jwt,
                )
            )

    async def test_unknown_emoji_raises(
        self,
        handler: SetReactionsCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        with pytest.raises(InvalidReactionError):
            await handler.handle(
                SetReactionsCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emojis=("👍", "bogus"),
                    user_jwt_data=user_jwt,
                )
            )

    async def test_non_member_raises(
        self,
        handler: SetReactionsCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        with pytest.raises(NotFoundChatError):
            await handler.handle(
                SetReactionsCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emojis=("👍",),
                    user_jwt_data=make_user_jwt(id="999"),
                )
            )

    async def test_replace_on_nonexistent_message_raises(
        self,
        handler: SetReactionsCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundMessageError):
            await handler.handle(
                SetReactionsCommand(
                    chat_id=group_chat.id,
                    message_id=uuid4(),
                    emojis=("👍",),
                    user_jwt_data=user_jwt,
                )
            )
