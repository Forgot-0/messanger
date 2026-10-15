import pytest
from dishka import AsyncContainer

from app.chats.commands.chats.set_username import SetChatUsernameCommand, SetChatUsernameCommandHandler
from app.chats.commands.chats.update import UpdateChatCommand, UpdateChatCommandHandler
from app.chats.exceptions import (
    AccessDeniedChatError,
    ChatUsernameNotAllowedError,
    ChatUsernameTakenError,
    InvalidChatUsernameError,
    NotFoundChatUsernameError,
)
from app.chats.models.chat import Chat, ChatType, UpdatedChatEvent
from app.chats.queries.chats.get_by_username import GetChatByUsernameQuery, GetChatByUsernameQueryHandler
from app.chats.queries.chats.search_public import SearchPublicChatsQuery, SearchPublicChatsQueryHandler
from app.chats.repositories.chat import ChatRepository
from app.core.services.auth.dto import UserJWTData
from tests.mocks import RecordingEventBus


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatUsername:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> SetChatUsernameCommandHandler:
        return await request_container.get(SetChatUsernameCommandHandler)

    async def test_set_username_on_public_group(
        self,
        handler: SetChatUsernameCommandHandler,
        chat_repository: ChatRepository,
        public_group_chat: Chat,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        dto = await handler.handle(SetChatUsernameCommand(
            user_jwt_data=user_jwt, chat_id=public_group_chat.id, username="@Python_News",
        ))

        assert dto.username == "Python_News"
        found = await chat_repository.get_by_username("python_news")
        assert found is not None and found.id == public_group_chat.id
        assert mock_event_bus.one_of_type(UpdatedChatEvent).username == "Python_News"

    async def test_username_is_unique_case_insensitively(
        self,
        handler: SetChatUsernameCommandHandler,
        create_group_chat,
        user_jwt: UserJWTData,
    ) -> None:
        first = await create_group_chat(members=[2], is_public=True, name="First")
        second = await create_group_chat(members=[2], is_public=True, name="Second")
        await handler.handle(SetChatUsernameCommand(
            user_jwt_data=user_jwt, chat_id=first.id, username="taken_name",
        ))

        with pytest.raises(ChatUsernameTakenError):
            await handler.handle(SetChatUsernameCommand(
                user_jwt_data=user_jwt, chat_id=second.id, username="TAKEN_name",
            ))

    async def test_private_chat_cannot_take_username(
        self,
        handler: SetChatUsernameCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(ChatUsernameNotAllowedError):
            await handler.handle(SetChatUsernameCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, username="secret_club",
            ))

    async def test_invalid_username(
        self,
        handler: SetChatUsernameCommandHandler,
        public_group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(InvalidChatUsernameError):
            await handler.handle(SetChatUsernameCommand(
                user_jwt_data=user_jwt, chat_id=public_group_chat.id, username="ab",
            ))

    async def test_member_without_update_right_cannot_set_username(
        self,
        handler: SetChatUsernameCommandHandler,
        public_group_chat: Chat,
        make_user_jwt,
    ) -> None:
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(SetChatUsernameCommand(
                user_jwt_data=make_user_jwt(id="2"), chat_id=public_group_chat.id, username="hijacked",
            ))

    async def test_clear_username_frees_it(
        self,
        handler: SetChatUsernameCommandHandler,
        chat_repository: ChatRepository,
        create_group_chat,
        user_jwt: UserJWTData,
    ) -> None:
        first = await create_group_chat(members=[2], is_public=True, name="First")
        second = await create_group_chat(members=[2], is_public=True, name="Second")
        await handler.handle(SetChatUsernameCommand(
            user_jwt_data=user_jwt, chat_id=first.id, username="moving_name",
        ))

        await handler.handle(SetChatUsernameCommand(
            user_jwt_data=user_jwt, chat_id=first.id, username=None,
        ))
        await handler.handle(SetChatUsernameCommand(
            user_jwt_data=user_jwt, chat_id=second.id, username="moving_name",
        ))

        found = await chat_repository.get_by_username("moving_name")
        assert found is not None and found.id == second.id

    async def test_making_chat_private_releases_username(
        self,
        handler: SetChatUsernameCommandHandler,
        request_container: AsyncContainer,
        chat_repository: ChatRepository,
        public_group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(SetChatUsernameCommand(
            user_jwt_data=user_jwt, chat_id=public_group_chat.id, username="going_private",
        ))

        update = await request_container.get(UpdateChatCommandHandler)
        dto = await update.handle(UpdateChatCommand(
            chat_id=public_group_chat.id, name=None, description=None, is_public=False,
            user_jwt_data=user_jwt,
        ))

        assert dto.username is None
        assert await chat_repository.get_by_username("going_private") is None


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestPublicChatLookup:

    @pytest.fixture
    async def set_username(self, request_container: AsyncContainer, user_jwt: UserJWTData):
        handler = await request_container.get(SetChatUsernameCommandHandler)

        async def _set(chat: Chat, username: str) -> None:
            await handler.handle(SetChatUsernameCommand(
                user_jwt_data=user_jwt, chat_id=chat.id, username=username,
            ))

        return _set

    async def test_resolve_by_username(
        self,
        request_container: AsyncContainer,
        set_username,
        public_group_chat: Chat,
        make_user_jwt,
    ) -> None:
        await set_username(public_group_chat, "Resolve_Me")
        handler = await request_container.get(GetChatByUsernameQueryHandler)

        outsider = await handler.handle(GetChatByUsernameQuery(
            user_jwt_data=make_user_jwt(id="77"), username="@resolve_me",
        ))
        member = await handler.handle(GetChatByUsernameQuery(
            user_jwt_data=make_user_jwt(id="2"), username="RESOLVE_ME",
        ))

        assert outsider.id == public_group_chat.id
        assert outsider.username == "Resolve_Me"
        assert outsider.is_member is False
        assert member.is_member is True

    async def test_unknown_username(
        self,
        request_container: AsyncContainer,
        user_jwt: UserJWTData,
    ) -> None:
        handler = await request_container.get(GetChatByUsernameQueryHandler)

        with pytest.raises(NotFoundChatUsernameError):
            await handler.handle(GetChatByUsernameQuery(user_jwt_data=user_jwt, username="nobody_here"))

    async def test_search_by_username_prefix_and_name(
        self,
        request_container: AsyncContainer,
        set_username,
        create_group_chat,
        user_jwt: UserJWTData,
    ) -> None:
        by_username = await create_group_chat(members=[2], is_public=True, name="Unrelated title")
        by_name = await create_group_chat(members=[2], is_public=True, name="Rustacean meetup")
        hidden = await create_group_chat(members=[2], is_public=False, name="Rustacean secret")
        await set_username(by_username, "rustlang_ru")

        handler = await request_container.get(SearchPublicChatsQueryHandler)
        result = await handler.handle(SearchPublicChatsQuery(user_jwt_data=user_jwt, q="rust"))

        ids = [item.id for item in result.items]
        assert by_username.id in ids
        assert by_name.id in ids
        assert hidden.id not in ids
        assert ids[0] == by_username.id or ids[0] == by_name.id

    async def test_exact_username_ranks_first(
        self,
        request_container: AsyncContainer,
        set_username,
        create_group_chat,
        user_jwt: UserJWTData,
    ) -> None:
        exact = await create_group_chat(members=[2], is_public=True, name="Exact")
        longer = await create_group_chat(members=[2, 3, 4, 5], is_public=True, name="Longer")
        await set_username(exact, "golang")
        await set_username(longer, "golang_jobs")

        handler = await request_container.get(SearchPublicChatsQueryHandler)
        result = await handler.handle(SearchPublicChatsQuery(user_jwt_data=user_jwt, q="@golang"))

        assert [item.id for item in result.items][:2] == [exact.id, longer.id]

    async def test_search_skips_direct_chats(
        self,
        request_container: AsyncContainer,
        db_session,
        user_jwt: UserJWTData,
    ) -> None:
        direct = Chat.create(
            created_by=1, members_ids=[2], chat_type=ChatType.DIRECT, name="Searchable direct", is_public=True,
        )
        db_session.add(direct)
        await db_session.commit()

        handler = await request_container.get(SearchPublicChatsQueryHandler)
        result = await handler.handle(SearchPublicChatsQuery(user_jwt_data=user_jwt, q="searchable"))

        assert direct.id not in [item.id for item in result.items]
