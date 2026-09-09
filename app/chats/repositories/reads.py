from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.chats.models.read_receipts import ReadReceipt
from app.core.db.repository import IRepository


@dataclass
class ReadReceiptRepository(IRepository[ReadReceipt]):

    async def mark_read(self, user_id: int, chat_id: UUID, message_seq: int) -> bool:
        insert_stmt = insert(ReadReceipt).values({
            "chat_id": chat_id,
            "user_id": user_id,
            "last_read_message_seq": message_seq,
        })

        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[ReadReceipt.chat_id, ReadReceipt.user_id],
            set_={
                "last_read_message_seq": insert_stmt.excluded.last_read_message_seq,
                "last_read_at": func.now(),
                "updated_at": func.now(),
            },
            where=(
                ReadReceipt.last_read_message_seq
                < insert_stmt.excluded.last_read_message_seq
            ),
        ).returning(ReadReceipt.chat_id)

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
