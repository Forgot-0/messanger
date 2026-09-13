import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.models.chat import Chat, ChatType
from app.chats.queries.messages.search import SearchMessagesQuery, SearchMessagesQueryHandler
from app.core.services.auth.dto import UserJWTData


@pytest.fixture
async def search_handler(request_container: AsyncContainer) -> SearchMessagesQueryHandler:
    return await request_container.get(SearchMessagesQueryHandler)


@pytest.fixture
async def foreign_chat(db_session: AsyncSession) -> Chat:
    """Чат, в котором user_jwt (id=1) не состоит вообще."""
    chat = Chat.create(
        created_by=42,
        members_ids=[43],
        chat_type=ChatType.GROUP,
        name="Foreign Group",
    )
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    return chat


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMessageSearchVisibility:

    async def test_finds_my_own_message(
        self,
        search_handler: SearchMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        await create_message(group_chat, user_jwt, "переговоры про бюджет")
        await create_message(group_chat, user_jwt, "совсем другое сообщение")

        result = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="бюджет")
        )

        assert [item.message.content for item in result.items] == ["переговоры про бюджет"]
        assert result.items[0].chat.id == group_chat.id
        assert result.items[0].chat.name == "Test Group"
        assert result.items[0].chat.type == ChatType.GROUP

    async def test_last_term_matches_by_prefix(
        self,
        search_handler: SearchMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        await create_message(group_chat, user_jwt, "подписали договор вчера")

        result = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="догов")
        )

        assert [item.message.content for item in result.items] == ["подписали договор вчера"]

    async def test_does_not_find_messages_of_a_chat_i_am_not_in(
        self,
        search_handler: SearchMessagesQueryHandler,
        foreign_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        await create_message(foreign_chat, make_user_jwt(id="42"), "секретный бюджет")

        result = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="бюджет")
        )

        assert result.items == []
        assert result.has_next is False

    async def test_explicit_foreign_chat_id_does_not_widen_the_scope(
        self,
        search_handler: SearchMessagesQueryHandler,
        foreign_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        await create_message(foreign_chat, make_user_jwt(id="42"), "секретный бюджет")

        result = await search_handler.handle(
            SearchMessagesQuery(
                user_jwt_data=user_jwt, q="бюджет", chat_id=foreign_chat.id
            )
        )

        assert result.items == []

    async def test_does_not_find_deleted_messages(
        self,
        search_handler: SearchMessagesQueryHandler,
        db_session: AsyncSession,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        alive = await create_message(group_chat, user_jwt, "живой бюджет")
        doomed = await create_message(group_chat, user_jwt, "удалённый бюджет")

        doomed.delete(deleted_by=int(user_jwt.id))
        await db_session.commit()

        result = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="бюджет")
        )

        assert [item.message.id for item in result.items] == [alive.id]

    async def test_does_not_find_messages_of_a_deleted_chat(
        self,
        search_handler: SearchMessagesQueryHandler,
        db_session: AsyncSession,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        await create_message(group_chat, user_jwt, "бюджет в мёртвом чате")

        group_chat.delete(deleted_by=int(user_jwt.id))
        await db_session.commit()

        result = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="бюджет")
        )

        assert result.items == []

    async def test_chat_id_narrows_the_selection(
        self,
        search_handler: SearchMessagesQueryHandler,
        group_chat: Chat,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        other = await create_group_chat(members=[2], name="Other Group")
        await create_message(group_chat, user_jwt, "бюджет здесь")
        await create_message(other, user_jwt, "бюджет там")

        everywhere = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="бюджет")
        )
        narrowed = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="бюджет", chat_id=other.id)
        )

        assert len(everywhere.items) == 2
        assert [item.message.content for item in narrowed.items] == ["бюджет там"]
        assert {item.chat.id for item in narrowed.items} == {other.id}


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMessageSearchPaging:

    async def test_cursor_neither_loses_nor_duplicates_rows(
        self,
        search_handler: SearchMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        created = [
            await create_message(group_chat, user_jwt, f"бюджет {i}")
            for i in range(5)
        ]
        expected = [msg.id for msg in reversed(created)]

        collected: list = []
        cursor = None
        for _ in range(5):
            page = await search_handler.handle(
                SearchMessagesQuery(
                    user_jwt_data=user_jwt, q="бюджет", limit=2, last_message_id=cursor
                )
            )
            collected.extend(item.message.id for item in page.items)
            if not page.has_next:
                break
            cursor = page.next_message_id

        assert collected == expected
        assert len(collected) == len(set(collected))

    async def test_last_page_reports_no_cursor(
        self,
        search_handler: SearchMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        await create_message(group_chat, user_jwt, "бюджет один")

        result = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="бюджет", limit=10)
        )

        assert result.has_next is False
        assert result.next_message_id is None

    async def test_limit_is_clamped_to_the_configured_maximum(
        self,
        search_handler: SearchMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        for i in range(3):
            await create_message(group_chat, user_jwt, f"бюджет {i}")

        zero = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="бюджет", limit=0)
        )
        huge = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="бюджет", limit=10_000)
        )

        assert len(zero.items) == 1
        assert len(huge.items) == 3


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMessageSearchHostileInput:

    @pytest.mark.parametrize(
        "q",
        [
            "it's",
            "'; DROP TABLE messages; --",
            "бюджет & !договор",
            "foo | bar",
            "(a <-> b):*",
            "*",
            "&|!()",
            "::::",
            '"кавычки"',
            "\\",
        ],
    )
    async def test_tsquery_operators_and_quotes_do_not_break_the_query(
        self,
        search_handler: SearchMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        q: str,
    ) -> None:
        await create_message(group_chat, user_jwt, "обычное сообщение про бюджет")

        result = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q=q)
        )

        assert isinstance(result.items, list)

    async def test_query_without_a_single_term_returns_an_empty_page(
        self,
        search_handler: SearchMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        await create_message(group_chat, user_jwt, "бюджет")

        result = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="&|!")
        )

        assert result.items == []
        assert result.has_next is False
        assert result.next_message_id is None

    async def test_operators_inside_the_query_are_treated_as_separators(
        self,
        search_handler: SearchMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        await create_message(group_chat, user_jwt, "бюджет и договор в одном сообщении")
        await create_message(group_chat, user_jwt, "только бюджет")

        # "&" схлопывается в разделитель, оба терма обязательны — второе
        # сообщение не подходит.
        result = await search_handler.handle(
            SearchMessagesQuery(user_jwt_data=user_jwt, q="бюджет & договор")
        )

        assert [item.message.content for item in result.items] == [
            "бюджет и договор в одном сообщении"
        ]
