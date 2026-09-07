from datetime import timedelta
from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.reactions.set import SetReactionCommand, SetReactionCommandHandler
from app.chats.exceptions import (
    AccessDeniedChatError,
    InvalidReactionError,
    NotFoundChatError,
    NotFoundMessageError,
    ReactionNotAllowedError,
    ReactionsDisabledError,
    TooManyReactionsError,
)
from app.chats.models.chat import Chat, ChatReactionsMode
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.reaction import MessageReactionRepository
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestSetReactionCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> SetReactionCommandHandler:
        return await request_container.get(SetReactionCommandHandler)

    async def test_member_adds_reaction(
        self,
        handler: SetReactionCommandHandler,
        reaction_repository: MessageReactionRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        await handler.handle(
            SetReactionCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emoji="👍",
                user_jwt_data=user_jwt,
            )
        )

        groups = await reaction_repository.get_current_groups(message.id)
        assert [(g.emoji, g.count) for g in groups] == [("👍", 1)]

    async def test_repeated_same_emoji_is_noop(
        self,
        handler: SetReactionCommandHandler,
        reaction_repository: MessageReactionRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")
        command = SetReactionCommand(
            chat_id=group_chat.id,
            message_id=message.id,
            emoji="👍",
            user_jwt_data=user_jwt,
        )

        await handler.handle(command)
        await handler.handle(command)

        groups = await reaction_repository.get_current_groups(message.id)
        assert [(g.emoji, g.count) for g in groups] == [("👍", 1)]

    async def test_user_can_add_multiple_distinct_reactions(
        self,
        handler: SetReactionCommandHandler,
        reaction_repository: MessageReactionRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        for emoji in ("👍", "🔥"):
            await handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji=emoji,
                    user_jwt_data=user_jwt,
                )
            )

        emojis = await reaction_repository.list_user_emojis(message.id, int(user_jwt.id))
        assert set(emojis) == {"👍", "🔥"}

    async def test_per_user_limit_exceeded_raises(
        self,
        handler: SetReactionCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")
        for emoji in ("👍", "🔥", "❤️"):
            await handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji=emoji,
                    user_jwt_data=user_jwt,
                )
            )

        with pytest.raises(TooManyReactionsError):
            await handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji="🎉",
                    user_jwt_data=user_jwt,
                )
            )

    async def test_unknown_emoji_raises(
        self,
        handler: SetReactionCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        with pytest.raises(InvalidReactionError):
            await handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji="not-an-emoji",
                    user_jwt_data=user_jwt,
                )
            )

    async def test_disabled_mode_raises(
        self,
        handler: SetReactionCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        db_session,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")
        group_chat.reactions_mode = ChatReactionsMode.NONE
        await db_session.commit()

        with pytest.raises(ReactionsDisabledError):
            await handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji="👍",
                    user_jwt_data=user_jwt,
                )
            )

    async def test_some_mode_rejects_emoji_outside_allowed(
        self,
        handler: SetReactionCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        db_session,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")
        group_chat.reactions_mode = ChatReactionsMode.SOME
        group_chat.allowed_reactions = ["🔥"]
        await db_session.commit()

        with pytest.raises(ReactionNotAllowedError):
            await handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji="👍",
                    user_jwt_data=user_jwt,
                )
            )

        await handler.handle(
            SetReactionCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emoji="🔥",
                user_jwt_data=user_jwt,
            )
        )

    async def test_muted_member_cannot_react(
        self,
        handler: SetReactionCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
        db_session,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")
        member = await chat_repository.get_member_chat(group_chat.id, 2, with_role=False)
        member.muted_until = now_utc() + timedelta(hours=1)
        await db_session.commit()

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji="👍",
                    user_jwt_data=make_user_jwt(id="2"),
                )
            )

    async def test_non_member_raises(
        self,
        handler: SetReactionCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        with pytest.raises(NotFoundChatError):
            await handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji="👍",
                    user_jwt_data=make_user_jwt(id="999"),
                )
            )

    async def test_react_to_nonexistent_message_raises(
        self,
        handler: SetReactionCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundMessageError):
            await handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=uuid4(),
                    emoji="👍",
                    user_jwt_data=user_jwt,
                )
            )
