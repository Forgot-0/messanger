from datetime import timedelta

import pytest
from dishka import AsyncContainer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.messages.mark_read import MarkAsReadCommand, MarkAsReadCommandHandler
from app.chats.config import chat_config
from app.chats.exceptions import (
    AccessDeniedChatError,
    ReadReceiptsUnavailableError,
    ReadReceiptsUnavailableReason,
)
from app.chats.models.chat import Chat
from app.chats.models.chat_members import ChatMember
from app.chats.models.message import Message
from app.chats.models.profile import ChatUserProfile
from app.chats.models.read_receipts import ReadReceiptMark
from app.chats.queries.messages.get_reads import GetMessageReadsQuery, GetMessageReadsQueryHandler
from app.chats.repositories.reads import ReadReceiptRepository
from app.chats.services.read_coalescer import ReadReceiptCoalesceQueue
from app.chats.services.read_flusher import ReadReceiptFlusher
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc

BASE = now_utc().replace(microsecond=0) - timedelta(hours=1)


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestReadMarksAreRecorded:

    @pytest.fixture(autouse=True)
    def immediate_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(chat_config, "READ_RECEIPTS_COALESCE_WINDOW_MS", 0)

    async def _read(
        self, request_container: AsyncContainer, chat: Chat, reader: UserJWTData, seq: int
    ) -> None:
        handler = await request_container.get(MarkAsReadCommandHandler)
        await handler.handle(MarkAsReadCommand(chat_id=chat.id, message_seq=seq, user_jwt_data=reader))
        queue = await request_container.get(ReadReceiptCoalesceQueue)
        flusher = await request_container.get(ReadReceiptFlusher)
        await flusher.flush(await queue.claim_due())

    async def _marks(self, db_session: AsyncSession, chat: Chat) -> list[tuple[int, int]]:
        result = await db_session.execute(
            select(ReadReceiptMark.user_id, ReadReceiptMark.seq)
            .where(ReadReceiptMark.chat_id == chat.id)
            .order_by(ReadReceiptMark.user_id, ReadReceiptMark.seq)
        )
        return [tuple(row) for row in result.all()]

    async def test_each_advance_in_a_small_group_leaves_a_mark(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
        db_session: AsyncSession,
    ) -> None:
        for i in range(3):
            await create_message(group_chat, user_jwt, f"m{i}")
        reader = make_user_jwt(id="2")

        await self._read(request_container, group_chat, reader, 1)
        await self._read(request_container, group_chat, reader, 3)
        await self._read(request_container, group_chat, reader, 2)

        assert await self._marks(db_session, group_chat) == [(2, 1), (2, 3)]

    async def test_direct_chats_and_large_groups_leave_no_marks(
        self,
        request_container: AsyncContainer,
        direct_chat: Chat,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        large = await create_group_chat([2, 3, 4])
        monkeypatch.setattr(chat_config, "READ_MARKS_MAX_MEMBERS", 3)
        for chat in (direct_chat, large):
            await create_message(chat, user_jwt, "hi")
            await self._read(request_container, chat, make_user_jwt(id="2"), 1)

        assert await self._marks(db_session, direct_chat) == []
        assert await self._marks(db_session, large) == []


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestGetMessageReads:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> GetMessageReadsQueryHandler:
        return await request_container.get(GetMessageReadsQueryHandler)

    @pytest.fixture
    async def chat(self, create_group_chat) -> Chat:
        return await create_group_chat([2, 3, 4])

    @pytest.fixture
    async def messages(self, chat: Chat, create_message, user_jwt: UserJWTData) -> list[Message]:
        return [await create_message(chat, user_jwt, f"m{i}") for i in range(3)]

    @pytest.fixture
    async def marks(self, chat: Chat, read_repository: ReadReceiptRepository, db_session: AsyncSession) -> None:
        await read_repository.add_marks([
            (chat.id, 2, 1, BASE + timedelta(minutes=1)),
            (chat.id, 3, 2, BASE + timedelta(minutes=2)),
            (chat.id, 2, 3, BASE + timedelta(minutes=3)),
            (chat.id, 1, 3, BASE + timedelta(minutes=4)),
        ])
        await db_session.commit()

    async def _readers(
        self, handler: GetMessageReadsQueryHandler, reader: UserJWTData, chat: Chat, message: Message
    ) -> list[tuple[int, object]]:
        dto = await handler.handle(
            GetMessageReadsQuery(user_jwt_data=reader, chat_id=chat.id, message_id=message.id)
        )
        assert dto.message_id == message.id
        return [(item.user_id, item.read_at) for item in dto.readers]

    async def test_each_reader_with_the_time_the_cursor_first_passed_the_message(
        self,
        handler: GetMessageReadsQueryHandler,
        chat: Chat,
        messages: list[Message],
        marks: None,
        user_jwt: UserJWTData,
    ) -> None:
        first, second, third = messages

        assert await self._readers(handler, user_jwt, chat, first) == [
            (3, BASE + timedelta(minutes=2)),
            (2, BASE + timedelta(minutes=1)),
        ]
        assert await self._readers(handler, user_jwt, chat, second) == [
            (2, BASE + timedelta(minutes=3)),
            (3, BASE + timedelta(minutes=2)),
        ]
        assert await self._readers(handler, user_jwt, chat, third) == [
            (2, BASE + timedelta(minutes=3)),
        ]

    async def test_banned_readers_disappear_and_profiles_are_attached(
        self,
        handler: GetMessageReadsQueryHandler,
        chat: Chat,
        messages: list[Message],
        marks: None,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        db_session.add(ChatUserProfile.create(user_id=2, username="reader_two", display_name="Two"))
        await db_session.execute(
            update(ChatMember)
            .where(ChatMember.chat_id == chat.id, ChatMember.user_id == 3)
            .values(banned_until=now_utc() + timedelta(days=1))
        )
        await db_session.commit()

        dto = await handler.handle(
            GetMessageReadsQuery(user_jwt_data=user_jwt, chat_id=chat.id, message_id=messages[0].id)
        )

        assert [item.user_id for item in dto.readers] == [2]
        profile = dto.readers[0].profile
        assert profile is not None
        assert profile.username == "reader_two"

    async def test_only_the_author_may_ask(
        self,
        handler: GetMessageReadsQueryHandler,
        chat: Chat,
        messages: list[Message],
        make_user_jwt,
    ) -> None:
        with pytest.raises(AccessDeniedChatError):
            await handler.handle(GetMessageReadsQuery(
                user_jwt_data=make_user_jwt(id="2"), chat_id=chat.id, message_id=messages[0].id
            ))

    async def test_direct_chat_is_not_supported(
        self,
        handler: GetMessageReadsQueryHandler,
        direct_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(direct_chat, user_jwt, "dm")

        with pytest.raises(ReadReceiptsUnavailableError) as exc:
            await handler.handle(
                GetMessageReadsQuery(user_jwt_data=user_jwt, chat_id=direct_chat.id, message_id=message.id)
            )
        assert exc.value.reason == ReadReceiptsUnavailableReason.CHAT_TYPE

    async def test_large_group_is_not_supported(
        self,
        handler: GetMessageReadsQueryHandler,
        chat: Chat,
        messages: list[Message],
        user_jwt: UserJWTData,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(chat_config, "READ_MARKS_MAX_MEMBERS", 3)

        with pytest.raises(ReadReceiptsUnavailableError) as exc:
            await handler.handle(
                GetMessageReadsQuery(user_jwt_data=user_jwt, chat_id=chat.id, message_id=messages[0].id)
            )
        assert exc.value.reason == ReadReceiptsUnavailableReason.CHAT_TOO_LARGE

    async def test_messages_past_retention_are_not_supported(
        self,
        handler: GetMessageReadsQueryHandler,
        chat: Chat,
        messages: list[Message],
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        old = messages[0]
        await db_session.execute(
            update(Message)
            .where(Message.id == old.id)
            .values(created_at=now_utc() - timedelta(days=chat_config.READ_MARKS_RETENTION_DAYS, hours=1))
        )
        await db_session.commit()
        await db_session.refresh(old)

        with pytest.raises(ReadReceiptsUnavailableError) as exc:
            await handler.handle(GetMessageReadsQuery(user_jwt_data=user_jwt, chat_id=chat.id, message_id=old.id))
        assert exc.value.reason == ReadReceiptsUnavailableReason.MESSAGE_TOO_OLD


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestReadMarksCleanup:

    async def test_cleanup_removes_only_expired_marks_in_batches(
        self,
        group_chat: Chat,
        read_repository: ReadReceiptRepository,
        db_session: AsyncSession,
    ) -> None:
        now = now_utc()
        await read_repository.add_marks(
            [(group_chat.id, 2, seq, now - timedelta(days=8)) for seq in range(1, 6)]
            + [(group_chat.id, 3, 1, now - timedelta(days=1))]
        )
        await db_session.commit()
        threshold = now - timedelta(days=chat_config.READ_MARKS_RETENTION_DAYS)

        assert await read_repository.cleanup_marks_older_than(threshold, batch_size=3) == 3
        assert await read_repository.cleanup_marks_older_than(threshold, batch_size=3) == 2
        assert await read_repository.cleanup_marks_older_than(threshold, batch_size=3) == 0

        remaining = await db_session.execute(
            select(ReadReceiptMark.user_id).where(ReadReceiptMark.chat_id == group_chat.id)
        )
        assert remaining.scalars().all() == [3]
