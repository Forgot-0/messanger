from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import delete, func, select, true, tuple_
from sqlalchemy.dialects.postgresql import insert

from app.chats.models.chat_members import ChatMember
from app.chats.models.profile import ChatUserProfile
from app.chats.models.read_receipts import ReadReceipt, ReadReceiptMark
from app.core.db.repository import IRepository


class MessageReader(NamedTuple):
    user_id: int
    read_at: datetime
    profile: ChatUserProfile | None


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

    async def mark_read_many(
        self, cursors: Sequence[tuple[UUID, int, int]]
    ) -> set[tuple[UUID, int]]:
        if not cursors:
            return set()

        insert_stmt = insert(ReadReceipt).values([
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "last_read_message_seq": message_seq,
            }
            for chat_id, user_id, message_seq in cursors
        ])

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
        ).returning(ReadReceipt.chat_id, ReadReceipt.user_id)

        result = await self.session.execute(stmt)
        return {(row.chat_id, row.user_id) for row in result}

    async def add_marks(self, marks: Sequence[tuple[UUID, int, int, datetime]]) -> None:
        if not marks:
            return

        stmt = insert(ReadReceiptMark).values([
            {"chat_id": chat_id, "user_id": user_id, "seq": seq, "read_at": read_at}
            for chat_id, user_id, seq, read_at in marks
        ]).on_conflict_do_nothing(
            index_elements=[ReadReceiptMark.chat_id, ReadReceiptMark.user_id, ReadReceiptMark.seq]
        )
        await self.session.execute(stmt)

    async def get_message_readers(
        self,
        chat_id: UUID,
        message_seq: int,
        exclude_user_id: int,
        limit: int,
    ) -> list[MessageReader]:
        first_mark = (
            select(ReadReceiptMark.read_at)
            .where(
                ReadReceiptMark.chat_id == ChatMember.chat_id,
                ReadReceiptMark.user_id == ChatMember.user_id,
                ReadReceiptMark.seq >= message_seq,
            )
            .order_by(ReadReceiptMark.seq.asc())
            .limit(1)
            .lateral("first_mark")
        )

        stmt = (
            select(ChatMember.user_id, first_mark.c.read_at, ChatUserProfile)
            .select_from(ChatMember)
            .join(first_mark, true())
            .outerjoin(ChatUserProfile, ChatUserProfile.user_id == ChatMember.user_id)
            .where(
                ChatMember.chat_id == chat_id,
                ChatMember.user_id != exclude_user_id,
                ChatMember.active_criteria(),
            )
            .order_by(first_mark.c.read_at.desc(), ChatMember.user_id.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [
            MessageReader(user_id=int(user_id), read_at=read_at, profile=profile)
            for user_id, read_at, profile in result.tuples()
        ]

    async def cleanup_marks_older_than(self, threshold: datetime, batch_size: int) -> int:
        expired = (
            select(ReadReceiptMark.chat_id, ReadReceiptMark.user_id, ReadReceiptMark.seq)
            .where(ReadReceiptMark.read_at < threshold)
            .limit(batch_size)
        )
        stmt = (
            delete(ReadReceiptMark)
            .where(
                tuple_(ReadReceiptMark.chat_id, ReadReceiptMark.user_id, ReadReceiptMark.seq).in_(expired)
            )
            .returning(ReadReceiptMark.seq)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        deleted = len(result.scalars().all())
        await self.session.commit()
        return deleted
