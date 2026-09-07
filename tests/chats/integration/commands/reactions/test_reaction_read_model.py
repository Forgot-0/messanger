import pytest
from dishka import AsyncContainer

from app.chats.commands.reactions.set import SetReactionCommand, SetReactionCommandHandler
from app.chats.models.chat import Chat
from app.chats.queries.messages.get_list import GetMessagesQuery, GetMessagesQueryHandler
from app.chats.queries.reactions.get_list import (
    GetMessageReactionsQuery,
    GetMessageReactionsQueryHandler,
)
from app.core.services.auth.dto import UserJWTData


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestReactionReadModel:

    @pytest.fixture
    async def set_handler(
        self,
        request_container: AsyncContainer,
    ) -> SetReactionCommandHandler:
        return await request_container.get(SetReactionCommandHandler)

    @pytest.fixture
    async def messages_handler(
        self,
        request_container: AsyncContainer,
    ) -> GetMessagesQueryHandler:
        return await request_container.get(GetMessagesQueryHandler)

    @pytest.fixture
    async def reactions_handler(
        self,
        request_container: AsyncContainer,
    ) -> GetMessageReactionsQueryHandler:
        return await request_container.get(GetMessageReactionsQueryHandler)

    async def test_message_list_includes_reaction_groups_sorted_by_count(
        self,
        set_handler: SetReactionCommandHandler,
        messages_handler: GetMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")

        await set_handler.handle(
            SetReactionCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emoji="🔥",
                user_jwt_data=user_jwt,
            )
        )
        for uid in ("2", "3"):
            await set_handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji="👍",
                    user_jwt_data=make_user_jwt(id=uid),
                )
            )

        result = await messages_handler.handle(
            GetMessagesQuery(user_jwt_data=user_jwt, chat_id=group_chat.id)
        )

        reactions = result.messages[0].reactions
        assert [(g.emoji, g.count) for g in reactions] == [("👍", 2), ("🔥", 1)]

    async def test_reacted_by_me_flag_is_per_user(
        self,
        set_handler: SetReactionCommandHandler,
        messages_handler: GetMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")
        await set_handler.handle(
            SetReactionCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emoji="🔥",
                user_jwt_data=user_jwt,
            )
        )
        await set_handler.handle(
            SetReactionCommand(
                chat_id=group_chat.id,
                message_id=message.id,
                emoji="👍",
                user_jwt_data=make_user_jwt(id="2"),
            )
        )

        result = await messages_handler.handle(
            GetMessagesQuery(user_jwt_data=user_jwt, chat_id=group_chat.id)
        )

        by_emoji = {g.emoji: g.reacted_by_me for g in result.messages[0].reactions}
        assert by_emoji == {"🔥": True, "👍": False}

    async def test_reactions_query_returns_users_for_emoji(
        self,
        set_handler: SetReactionCommandHandler,
        reactions_handler: GetMessageReactionsQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "React")
        for jwt in (user_jwt, make_user_jwt(id="2")):
            await set_handler.handle(
                SetReactionCommand(
                    chat_id=group_chat.id,
                    message_id=message.id,
                    emoji="👍",
                    user_jwt_data=jwt,
                )
            )

        result = await reactions_handler.handle(
            GetMessageReactionsQuery(
                user_jwt_data=user_jwt,
                chat_id=group_chat.id,
                message_id=message.id,
                emoji="👍",
            )
        )

        assert set(result.users) == {1, 2}
        assert [(g.emoji, g.count) for g in result.groups] == [("👍", 2)]
