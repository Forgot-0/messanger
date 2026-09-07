from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.chats.models.message import Message
from app.core.db.repository import IRepository


def _message_load_options() -> list:
    return [
        selectinload(Message.attachments),
        selectinload(Message.profile),
        selectinload(Message.reply_to).options(
            selectinload(Message.profile),
            selectinload(Message.attachments),
        ),
        selectinload(Message.forwarded_from).options(
            selectinload(Message.profile),
            selectinload(Message.attachments),
        ),
    ]


@dataclass
class MessageRepository(IRepository[Message]):

    async def get_by_id(
        self,
        message_id: UUID,
        with_attachment: bool = False,
    ) -> Message | None:
        stmt = select(Message).where(
            Message.id == message_id,
            Message.is_deleted.is_(False),
        )
        if with_attachment:
            stmt = stmt.options(*_message_load_options())

        result = await self.session.execute(stmt)
        return result.scalar()

    async def create(self, message: Message) -> None:
        self.session.add(message)

    async def get_paginated_chat_messages(
        self,
        chat_id: UUID,
        cursor_seq: int | None,
        limit: int,
        direction: Literal["backward", "forward"] = "backward"
    ) -> list[Message]:
        stmt = select(Message).where(
            Message.chat_id == chat_id,
            Message.is_deleted.is_(False),
        ).options(*_message_load_options())

        if cursor_seq is not None:
            if direction == "backward":
                stmt = stmt.where(Message.seq < cursor_seq)
                stmt = stmt.order_by(Message.seq.desc())
            else:
                stmt = stmt.where(Message.seq > cursor_seq)
                stmt = stmt.order_by(Message.seq.asc())
        else:
            stmt = stmt.order_by(Message.seq.desc())

        stmt = stmt.limit(limit + 1)

        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def get_chat_messages_after_seq(
        self,
        chat_id: UUID,
        last_seq: int,
        limit: int,
    ) -> list[Message]:
        stmt = (
            select(Message)
            .where(
                Message.chat_id == chat_id,
                Message.seq > last_seq,
                Message.is_deleted.is_(False),
            )
            .order_by(Message.seq.asc())
            .limit(limit + 1)
            .options(*_message_load_options())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def get_message_context(
        self,
        chat_id: UUID,
        target_seq: int,
        limit: int = 20
    ) -> list[Message]:
        half = limit // 2

        older_stmt = (
            select(Message)
            .where(and_(Message.chat_id == chat_id, Message.seq <= target_seq), Message.is_deleted.is_(False))
            .order_by(Message.seq.desc())
            .limit(half)
            .options(*_message_load_options())
        )

        newer_stmt = (
            select(Message)
            .where(and_(Message.chat_id == chat_id, Message.seq > target_seq))
            .order_by(Message.seq.asc())
            .limit(half)
            .options(*_message_load_options())
        )

        older_res = await self.session.execute(older_stmt)
        newer_res = await self.session.execute(newer_stmt)

        combined = list(older_res.scalars().all()) + list(newer_res.scalars().all())

        return combined
