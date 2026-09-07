from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from app.chats.models.read_receipts import ReadReceipt
from app.core.db.repository import IRepository


@dataclass
class ReadReceiptRepository(IRepository[ReadReceipt]):

    async def mark_read(self, user_id: int, chat_id: UUID, message_seq: int) -> None:
        stmt = insert(ReadReceipt).values({
            "user_id": user_id,
            "chat_id": chat_id,
            "last_read_message_seq": message_seq
        })

        stmt = stmt.on_conflict_do_update(
            constraint="uq_read_receipt",
            set_={
                "last_read_message_seq": stmt.excluded.last_read_message_seq,
            },
            where=(
                ReadReceipt.last_read_message_seq
                < stmt.excluded.last_read_message_seq
            ),
        )
        await self.session.execute(stmt)
