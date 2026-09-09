import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.models.message import ReadedMessageEvent
from app.chats.repositories.reads import ReadReceiptRepository
from app.chats.services.read_coalescer import PendingReadCursor
from app.core.events.service import BaseEventBus

logger = logging.getLogger(__name__)


@dataclass
class ReadReceiptFlusher:
    session: AsyncSession
    read_receipt_repository: ReadReceiptRepository
    event_bus: BaseEventBus

    async def flush(self, cursors: list[PendingReadCursor]) -> int:
        if not cursors:
            return 0

        advanced = await self.read_receipt_repository.mark_read_many([
            (cursor.chat_id, cursor.user_id, cursor.message_seq)
            for cursor in cursors
        ])

        events = [
            ReadedMessageEvent(
                chat_id=str(cursor.chat_id),
                seq=cursor.message_seq,
                reader_id=cursor.user_id,
            )
            for cursor in cursors
            if cursor.support_read_event
            and (cursor.chat_id, cursor.user_id) in advanced
        ]

        if events:
            await self.event_bus.publish(events)

        await self.session.commit()

        logger.debug(
            "Read receipts flushed",
            extra={
                "claimed": len(cursors),
                "advanced": len(advanced),
                "events": len(events),
            },
        )
        return len(advanced)
