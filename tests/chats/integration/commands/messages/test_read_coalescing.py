import pytest
from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.messages.mark_read import MarkAsReadCommand, MarkAsReadCommandHandler
from app.chats.config import chat_config
from app.chats.models.chat import Chat
from app.chats.models.read_receipts import ReadReceipt
from app.chats.services.read_coalescer import ReadReceiptCoalesceQueue
from app.chats.services.read_flusher import ReadReceiptFlusher
from app.core.outbox.model import OutboxMessage
from app.core.services.auth.dto import UserJWTData

CHAT_SEQ_COUNTER = 50


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestReadReceiptCoalescing:

    @pytest.fixture(autouse=True)
    def immediate_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(chat_config, "READ_RECEIPTS_COALESCE_WINDOW_MS", 0)

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> MarkAsReadCommandHandler:
        return await request_container.get(MarkAsReadCommandHandler)

    @pytest.fixture
    async def queue(self, request_container: AsyncContainer) -> ReadReceiptCoalesceQueue:
        return await request_container.get(ReadReceiptCoalesceQueue)

    @pytest.fixture
    async def flusher(self, request_container: AsyncContainer) -> ReadReceiptFlusher:
        return await request_container.get(ReadReceiptFlusher)

    @pytest.fixture
    async def chat(self, group_chat: Chat, db_session: AsyncSession) -> Chat:
        group_chat.seq_counter = CHAT_SEQ_COUNTER
        await db_session.commit()
        return group_chat

    async def _receipt(
        self, db_session: AsyncSession, chat: Chat, user_id: int
    ) -> ReadReceipt | None:
        result = await db_session.execute(
            select(ReadReceipt).where(
                ReadReceipt.chat_id == chat.id,
                ReadReceipt.user_id == user_id,
            )
        )
        return result.scalar()

    async def _read_events(
        self, db_session: AsyncSession, chat: Chat
    ) -> list[OutboxMessage]:
        result = await db_session.execute(
            select(OutboxMessage).where(
                OutboxMessage.aggregate_id == str(chat.id),
                OutboxMessage.event_name == "chats.message.readed",
            )
        )
        return list(result.scalars().all())

    async def test_request_writes_nothing_to_postgres(
        self,
        handler: MarkAsReadCommandHandler,
        chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        await handler.handle(
            MarkAsReadCommand(chat_id=chat.id, message_seq=7, user_jwt_data=user_jwt)
        )

        assert await self._receipt(db_session, chat, int(user_jwt.id)) is None
        assert await self._read_events(db_session, chat) == []

    async def test_flush_writes_cursor_and_publishes_event(
        self,
        handler: MarkAsReadCommandHandler,
        queue: ReadReceiptCoalesceQueue,
        flusher: ReadReceiptFlusher,
        chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        await handler.handle(
            MarkAsReadCommand(chat_id=chat.id, message_seq=7, user_jwt_data=user_jwt)
        )

        cursors = await queue.claim_due()
        assert len(cursors) == 1
        assert await flusher.flush(cursors) == 1

        receipt = await self._receipt(db_session, chat, int(user_jwt.id))
        assert receipt is not None
        assert receipt.last_read_message_seq == 7

        events = await self._read_events(db_session, chat)
        assert len(events) == 1
        assert events[0].payload["seq"] == 7
        assert events[0].payload["reader_id"] == int(user_jwt.id)

    async def test_burst_collapses_into_one_write_and_one_event(
        self,
        handler: MarkAsReadCommandHandler,
        queue: ReadReceiptCoalesceQueue,
        flusher: ReadReceiptFlusher,
        chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        for seq in (3, 8, 15, 21, 34):
            await handler.handle(
                MarkAsReadCommand(chat_id=chat.id, message_seq=seq, user_jwt_data=user_jwt)
            )

        cursors = await queue.claim_due()
        assert len(cursors) == 1
        assert cursors[0].message_seq == 34

        await flusher.flush(cursors)

        receipt = await self._receipt(db_session, chat, int(user_jwt.id))
        assert receipt is not None
        assert receipt.last_read_message_seq == 34

        events = await self._read_events(db_session, chat)
        assert len(events) == 1
        assert events[0].payload["seq"] == 34

    async def test_lower_seq_never_overwrites_pending_cursor(
        self,
        handler: MarkAsReadCommandHandler,
        queue: ReadReceiptCoalesceQueue,
        chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await handler.handle(
            MarkAsReadCommand(chat_id=chat.id, message_seq=20, user_jwt_data=user_jwt)
        )
        await handler.handle(
            MarkAsReadCommand(chat_id=chat.id, message_seq=5, user_jwt_data=user_jwt)
        )

        cursors = await queue.claim_due()
        assert len(cursors) == 1
        assert cursors[0].message_seq == 20

    async def test_enqueue_reports_whether_cursor_was_superseded(
        self, queue: ReadReceiptCoalesceQueue, chat: Chat, user_jwt: UserJWTData
    ) -> None:
        user_id = int(user_jwt.id)

        assert await queue.enqueue(chat.id, user_id, 10, True) is True
        assert await queue.enqueue(chat.id, user_id, 4, True) is False
        assert await queue.enqueue(chat.id, user_id, 10, True) is False
        assert await queue.enqueue(chat.id, user_id, 11, True) is True

    async def test_claim_drains_the_window(
        self, queue: ReadReceiptCoalesceQueue, chat: Chat, user_jwt: UserJWTData
    ) -> None:
        await queue.enqueue(chat.id, int(user_jwt.id), 9, True)

        assert len(await queue.claim_due()) == 1
        assert await queue.claim_due() == []

    async def test_requeue_returns_failed_cursors_to_the_window(
        self, queue: ReadReceiptCoalesceQueue, chat: Chat, user_jwt: UserJWTData
    ) -> None:
        await queue.enqueue(chat.id, int(user_jwt.id), 12, True)
        claimed = await queue.claim_due()
        assert len(claimed) == 1

        await queue.requeue(claimed)

        again = await queue.claim_due()
        assert len(again) == 1
        assert again[0].message_seq == 12

    async def test_flush_batches_many_chats_in_one_go(
        self,
        queue: ReadReceiptCoalesceQueue,
        flusher: ReadReceiptFlusher,
        create_group_chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        chats = [await create_group_chat(members=[2, 3], name=f"Chat {i}") for i in range(3)]
        user_id = int(user_jwt.id)

        for index, item in enumerate(chats, start=1):
            await queue.enqueue(item.id, user_id, index, True)

        cursors = await queue.claim_due()
        assert len(cursors) == 3
        assert await flusher.flush(cursors) == 3

        for index, item in enumerate(chats, start=1):
            receipt = await self._receipt(db_session, item, user_id)
            assert receipt is not None
            assert receipt.last_read_message_seq == index

    async def test_chat_without_read_support_writes_cursor_but_no_event(
        self,
        queue: ReadReceiptCoalesceQueue,
        flusher: ReadReceiptFlusher,
        chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        await queue.enqueue(chat.id, int(user_jwt.id), 6, support_read_event=False)

        cursors = await queue.claim_due()
        await flusher.flush(cursors)

        receipt = await self._receipt(db_session, chat, int(user_jwt.id))
        assert receipt is not None
        assert receipt.last_read_message_seq == 6
        assert await self._read_events(db_session, chat) == []
