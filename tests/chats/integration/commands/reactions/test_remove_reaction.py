from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.reactions.remove import (
    RemoveReactionCommand,
    RemoveReactionCommandHandler,
)
from app.chats.exceptions import NotFoundChatError, NotFoundMessageError
from app.chats.models.chat import Chat
from app.chats.repositories.reaction import MessageReactionRepository
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestRemoveReactionCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> RemoveReactionCommandHandler:
        return await request_container.get(RemoveReactionCommandHandler)

    async def test_member_removes_reaction(
        self,
        handler: RemoveReactionCommandHandler,
        reaction_repository: MessageReactionRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")
        await reaction_repository.add_reaction(
            chat_id=group_chat.id,
            message_id=message.id,
            user_id=int(user_jwt.id),
            emoji="👍",
        )

        await handler.handle(
            RemoveReactionCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emoji="👍",
                user_jwt_data=user_jwt,
            )
        )

        assert await reaction_repository.get_current_groups(message.id) == []

    async def test_remove_absent_reaction_is_noop(
        self,
        handler: RemoveReactionCommandHandler,
        reaction_repository: MessageReactionRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        await handler.handle(
            RemoveReactionCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emoji="👍",
                user_jwt_data=user_jwt,
            )
        )

        assert await reaction_repository.get_current_groups(message.id) == []

    async def test_remove_keeps_other_users_reaction(
        self,
        handler: RemoveReactionCommandHandler,
        reaction_repository: MessageReactionRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")
        for uid in (int(user_jwt.id), 2):
            await reaction_repository.add_reaction(
                chat_id=group_chat.id,
                message_id=message.id,
                user_id=uid,
                emoji="👍",
            )

        await handler.handle(
            RemoveReactionCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emoji="👍",
                user_jwt_data=user_jwt,
            )
        )

        groups = await reaction_repository.get_current_groups(message.id)
        assert [(g.emoji, g.count) for g in groups] == [("👍", 1)]

    async def test_non_member_raises(
        self,
        handler: RemoveReactionCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        with pytest.raises(NotFoundChatError):
            await handler.handle(
                RemoveReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji="👍",
                    user_jwt_data=make_user_jwt(id="999"),
                )
            )

    async def test_remove_from_nonexistent_message_raises(
        self,
        handler: RemoveReactionCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundMessageError):
            await handler.handle(
                RemoveReactionCommand(
                    chat_id=group_chat.id,
                    message_id=uuid4(),
                    emoji="👍",
                    user_jwt_data=user_jwt,
                )
            )
