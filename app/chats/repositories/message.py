from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.chats.models.chat import Chat
from app.chats.models.chat_members import ChatMember
from app.chats.models.message import Message
from app.core.db.repository import IRepository


def message_load_options() -> list:
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
            stmt = stmt.options(*message_load_options())

        result = await self.session.execute(stmt)
        return result.scalar()

    async def get_many_in_chat(
        self,
        chat_id: UUID,
        message_ids: Sequence[UUID],
    ) -> list[Message]:
        if not message_ids:
            return []

        stmt = (
            select(Message)
            .where(
                Message.chat_id == chat_id,
                Message.id.in_(list(message_ids)),
                Message.is_deleted.is_(False),
            )
            .options(selectinload(Message.attachments))
            .order_by(Message.seq.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, message: Message) -> None:
        self.session.add(message)

    async def create_many(self, messages: Sequence[Message]) -> None:
        self.session.add_all(messages)

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
        ).options(*message_load_options())

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
            .options(*message_load_options())
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
            .options(*message_load_options())
        )

        newer_stmt = (
            select(Message)
            .where(and_(Message.chat_id == chat_id, Message.seq > target_seq), Message.is_deleted.is_(False))
            .order_by(Message.seq.asc())
            .limit(half)
            .options(*message_load_options())
        )

        older_res = await self.session.execute(older_stmt)
        newer_res = await self.session.execute(newer_stmt)

        combined = list(older_res.scalars().all()) + list(newer_res.scalars().all())

        return combined

    async def search_visible(
        self,
        user_id: int,
        tsquery: str,
        limit: int,
        chat_id: UUID | None = None,
        last_message_id: UUID | None = None,
    ) -> list[tuple[Message, Chat]]:
        conditions = [
            ChatMember.active_criteria(),
            Message.is_deleted.is_(False),
            Chat.deleted_at.is_(None),
            func.to_tsvector("simple", Message.content).op("@@")(
                func.to_tsquery("simple", tsquery)
            ),
        ]
        if chat_id is not None:
            conditions.append(Message.chat_id == chat_id)
        if last_message_id is not None:
            conditions.append(Message.id < last_message_id)

        stmt = (
            select(Message, Chat)
            .join(Chat, Chat.id == Message.chat_id)
            .join(
                ChatMember,
                and_(ChatMember.chat_id == Message.chat_id, ChatMember.user_id == user_id),
            )
            .where(*conditions)
            .options(selectinload(Message.profile))
            .order_by(Message.id.desc())
            .limit(limit + 1)
        )

        result = await self.session.execute(stmt)
        return list(result.tuples())

    async def get_link_messages_page(
        self,
        chat_id: UUID,
        limit: int,
        before_seq: int | None = None,
    ) -> list[Message]:
        # Ровно в форме предиката ix_messages_chat_links: `IS TRUE`/`IS FALSE` планировщик
        # не сводит к `has_links AND is_deleted = false` и уходит в seq scan.
        conditions = [
            Message.chat_id == chat_id,
            Message.has_links,
            ~Message.is_deleted,
        ]
        if before_seq is not None:
            conditions.append(Message.seq < before_seq)

        stmt = (
            select(Message)
            .where(*conditions)
            .order_by(Message.seq.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
