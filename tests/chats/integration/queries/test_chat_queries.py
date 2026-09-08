from uuid import uuid4

import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.messages.mark_read import MarkAsReadCommand, MarkAsReadCommandHandler
from app.chats.exceptions import NotChatMemberError, NotFoundChatError, NotFoundMessageError
from app.chats.models.chat import Chat
from app.chats.queries.chats.get_detail import GetChatDetailQuery, GetChatDetailQueryHandler
from app.chats.queries.chats.get_list import GetListChatUserQuery, GetListChatUserQueryHandler
from app.chats.queries.chats.get_members import (
    GetChatMembersQuery,
    GetChatMembersQueryHandler,
)
from app.chats.queries.messages.get_context import (
    GetMessageContextQuery,
    GetMessageContextQueryHandler,
)
from app.chats.queries.messages.get_detail import (
    GetMessageDetailQuery,
    GetMessageDetailQueryHandler,
)
from app.core.services.auth.dto import UserJWTData


@pytest.fixture
async def list_handler(request_container: AsyncContainer) -> GetListChatUserQueryHandler:
    return await request_container.get(GetListChatUserQueryHandler)


@pytest.fixture
async def context_handler(
    request_container: AsyncContainer,
) -> GetMessageContextQueryHandler:
    return await request_container.get(GetMessageContextQueryHandler)


@pytest.fixture
async def mark_read_handler(
    request_container: AsyncContainer,
) -> MarkAsReadCommandHandler:
    return await request_container.get(MarkAsReadCommandHandler)


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestUnreadCount:

    async def test_chat_without_messages_has_no_unread(
        self,
        list_handler: GetListChatUserQueryHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        (chat,) = [c for c in result.chats if c.id == group_chat.id]
        assert chat.unread_count == 0

    async def test_never_read_chat_counts_every_message(
        self,
        list_handler: GetListChatUserQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        for i in range(3):
            await create_message(group_chat, make_user_jwt(id="2"), f"m{i}")

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        (chat,) = [c for c in result.chats if c.id == group_chat.id]
        assert chat.unread_count == 3
        assert chat.last_read is None

    async def test_reading_everything_zeroes_the_counter(
        self,
        list_handler: GetListChatUserQueryHandler,
        mark_read_handler: MarkAsReadCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        for i in range(3):
            await create_message(group_chat, make_user_jwt(id="2"), f"m{i}")

        await mark_read_handler.handle(
            MarkAsReadCommand(chat_id=group_chat.id, message_seq=3, user_jwt_data=user_jwt)
        )

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )
        (chat,) = [c for c in result.chats if c.id == group_chat.id]
        assert chat.unread_count == 0

    async def test_partial_read_leaves_the_tail(
        self,
        list_handler: GetListChatUserQueryHandler,
        mark_read_handler: MarkAsReadCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        for i in range(5):
            await create_message(group_chat, make_user_jwt(id="2"), f"m{i}")

        await mark_read_handler.handle(
            MarkAsReadCommand(chat_id=group_chat.id, message_seq=2, user_jwt_data=user_jwt)
        )

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )
        (chat,) = [c for c in result.chats if c.id == group_chat.id]
        assert chat.unread_count == 3

    async def test_read_cursor_ahead_of_the_counter_does_not_go_negative(
        self,
        list_handler: GetListChatUserQueryHandler,
        mark_read_handler: MarkAsReadCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        await create_message(group_chat, make_user_jwt(id="2"), "one")

        await mark_read_handler.handle(
            MarkAsReadCommand(chat_id=group_chat.id, message_seq=999, user_jwt_data=user_jwt)
        )

        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )
        (chat,) = [c for c in result.chats if c.id == group_chat.id]
        assert chat.unread_count == 0

    async def test_unread_is_counted_per_member(
        self,
        list_handler: GetListChatUserQueryHandler,
        mark_read_handler: MarkAsReadCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        peer = make_user_jwt(id="2")
        for i in range(4):
            await create_message(group_chat, peer, f"m{i}")

        await mark_read_handler.handle(
            MarkAsReadCommand(chat_id=group_chat.id, message_seq=4, user_jwt_data=user_jwt)
        )

        mine = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )
        theirs = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=peer, limit=10)
        )

        assert [c.unread_count for c in mine.chats if c.id == group_chat.id] == [0]
        assert [c.unread_count for c in theirs.chats if c.id == group_chat.id] == [4]


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatListPaging:

    async def test_limit_is_clamped_to_a_sane_range(
        self,
        list_handler: GetListChatUserQueryHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        zero = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=0)
        )
        huge = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=1000)
        )

        assert len(zero.chats) == 1
        assert len(huge.chats) == 1

    async def test_last_page_reports_no_cursor(
        self,
        list_handler: GetListChatUserQueryHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=user_jwt, limit=10)
        )

        assert result.has_next is False
        assert result.next_chat_id is None
        assert result.next_date is None

    async def test_user_without_chats_gets_an_empty_page(
        self,
        list_handler: GetListChatUserQueryHandler,
        make_user_jwt,
    ) -> None:
        result = await list_handler.handle(
            GetListChatUserQuery(user_jwt_data=make_user_jwt(id="9999"), limit=10)
        )

        assert result.chats == []
        assert result.has_next is False


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMessageContext:

    async def test_context_is_centred_on_the_target(
        self,
        context_handler: GetMessageContextQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        for i in range(10):
            await create_message(group_chat, user_jwt, f"m{i}")

        result = await context_handler.handle(
            GetMessageContextQuery(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_seq=5, limit=4
            )
        )

        seqs = [m.seq for m in result.messages]
        assert 5 in seqs
        assert seqs == sorted(seqs)

    async def test_messages_always_come_back_ordered_by_seq(
        self,
        context_handler: GetMessageContextQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        for i in range(6):
            await create_message(group_chat, user_jwt, f"m{i}")

        result = await context_handler.handle(
            GetMessageContextQuery(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_seq=3
            )
        )

        seqs = [m.seq for m in result.messages]
        assert seqs == sorted(seqs)

    async def test_target_at_the_very_beginning_works(
        self,
        context_handler: GetMessageContextQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        for i in range(5):
            await create_message(group_chat, user_jwt, f"m{i}")

        result = await context_handler.handle(
            GetMessageContextQuery(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_seq=1
            )
        )

        assert 1 in [m.seq for m in result.messages]

    async def test_target_beyond_the_history_falls_back_to_the_tail(
        self,
        context_handler: GetMessageContextQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        for i in range(3):
            await create_message(group_chat, user_jwt, f"m{i}")

        result = await context_handler.handle(
            GetMessageContextQuery(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_seq=10_000
            )
        )

        assert [m.seq for m in result.messages] == [1, 2, 3]

    async def test_deleted_messages_do_not_leak_into_the_context(
        self,
        context_handler: GetMessageContextQueryHandler,
        request_container: AsyncContainer,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        from app.chats.commands.messages.delete import (
            DeleteMessageCommand,
            DeleteMessageCommandHandler,
        )

        messages = [
            await create_message(group_chat, user_jwt, f"m{i}") for i in range(6)
        ]
        delete_handler = await request_container.get(DeleteMessageCommandHandler)

        await delete_handler.handle(
            DeleteMessageCommand(
                chat_id=group_chat.id,
                message_id=messages[4].id,
                user_jwt_data=user_jwt,
            )
        )

        result = await context_handler.handle(
            GetMessageContextQuery(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_seq=3, limit=20
            )
        )

        assert messages[4].seq not in [m.seq for m in result.messages]

    async def test_empty_chat_returns_no_messages(
        self,
        context_handler: GetMessageContextQueryHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        result = await context_handler.handle(
            GetMessageContextQuery(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_seq=1
            )
        )

        assert result.messages == []
        assert result.has_next is False

    async def test_outsider_is_refused(
        self,
        context_handler: GetMessageContextQueryHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        with pytest.raises(NotChatMemberError):
            await context_handler.handle(
                GetMessageContextQuery(
                    user_jwt_data=make_user_jwt(id="9999"),
                    chat_id=group_chat.id,
                    target_seq=1,
                )
            )

    async def test_banned_member_is_refused(
        self,
        context_handler: GetMessageContextQueryHandler,
        chat_repository,
        db_session: AsyncSession,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        member.ban(banned_by=1)
        await db_session.commit()

        with pytest.raises(NotChatMemberError):
            await context_handler.handle(
                GetMessageContextQuery(
                    user_jwt_data=make_user_jwt(id="2"),
                    chat_id=group_chat.id,
                    target_seq=1,
                )
            )


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatDetailAndMembers:

    @pytest.fixture
    async def detail_handler(
        self, request_container: AsyncContainer
    ) -> GetChatDetailQueryHandler:
        return await request_container.get(GetChatDetailQueryHandler)

    @pytest.fixture
    async def members_handler(
        self, request_container: AsyncContainer
    ) -> GetChatMembersQueryHandler:
        return await request_container.get(GetChatMembersQueryHandler)

    async def test_detail_is_returned_for_a_member(
        self,
        detail_handler: GetChatDetailQueryHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        result = await detail_handler.handle(
            GetChatDetailQuery(user_jwt_data=user_jwt, chat_id=group_chat.id)
        )

        assert result.id == group_chat.id
        assert result.member_count == group_chat.member_count

    async def test_detail_of_a_missing_chat_raises(
        self,
        detail_handler: GetChatDetailQueryHandler,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundChatError):
            await detail_handler.handle(
                GetChatDetailQuery(user_jwt_data=user_jwt, chat_id=uuid4())
            )

    async def test_detail_is_refused_to_outsiders(
        self,
        detail_handler: GetChatDetailQueryHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        with pytest.raises(NotChatMemberError):
            await detail_handler.handle(
                GetChatDetailQuery(
                    user_jwt_data=make_user_jwt(id="9999"), chat_id=group_chat.id
                )
            )

    async def test_members_list_contains_everyone(
        self,
        members_handler: GetChatMembersQueryHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        result = await members_handler.handle(
            GetChatMembersQuery(user_jwt_data=user_jwt, chat_id=group_chat.id)
        )

        assert {m.user_id for m in result.members} == {1, 2, 3}

    async def test_presence_is_empty_when_redis_knows_nobody(
        self,
        members_handler: GetChatMembersQueryHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        result = await members_handler.handle(
            GetChatMembersQuery(
                user_jwt_data=user_jwt, chat_id=group_chat.id, include_presence=True
            )
        )

        assert all(p.is_online is False for p in result.presence)

    async def test_members_are_refused_to_outsiders(
        self,
        members_handler: GetChatMembersQueryHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        with pytest.raises((NotChatMemberError, NotFoundChatError)):
            await members_handler.handle(
                GetChatMembersQuery(
                    user_jwt_data=make_user_jwt(id="9999"), chat_id=group_chat.id
                )
            )


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMessageDetail:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> GetMessageDetailQueryHandler:
        return await request_container.get(GetMessageDetailQueryHandler)

    async def test_message_is_returned_to_a_member(
        self,
        handler: GetMessageDetailQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "деталь")

        result = await handler.handle(
            GetMessageDetailQuery(
                user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=message.id
            )
        )

        assert result.id == message.id
        assert result.content == "деталь"

    async def test_missing_message_raises(
        self,
        handler: GetMessageDetailQueryHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundMessageError):
            await handler.handle(
                GetMessageDetailQuery(
                    user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=uuid4()
                )
            )

    async def test_message_from_another_chat_is_not_reachable(
        self,
        handler: GetMessageDetailQueryHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        chat_a = await create_group_chat([2, 3])
        chat_b = await create_group_chat([2, 3])
        message = await create_message(chat_a, user_jwt, "в чате A")

        with pytest.raises(NotFoundMessageError):
            await handler.handle(
                GetMessageDetailQuery(
                    user_jwt_data=user_jwt, chat_id=chat_b.id, message_id=message.id
                )
            )

    async def test_outsider_is_refused(
        self,
        handler: GetMessageDetailQueryHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "секрет")

        with pytest.raises(NotChatMemberError):
            await handler.handle(
                GetMessageDetailQuery(
                    user_jwt_data=make_user_jwt(id="9999"),
                    chat_id=group_chat.id,
                    message_id=message.id,
                )
            )
