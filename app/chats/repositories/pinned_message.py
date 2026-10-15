from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, select

from app.chats.models.message import Message
from app.chats.models.pinned_message import ChatPinnedMessage
from app.chats.repositories.message import message_load_options
from app.core.db.repository import IRepository


@dataclass
class ChatPinnedMessageRepository(IRepository[ChatPinnedMessage]):

    async def get(self, chat_id: UUID, message_id: UUID) -> ChatPinnedMessage | None:
        stmt = select(ChatPinnedMessage).where(
            ChatPinnedMessage.chat_id == chat_id,
            ChatPinnedMessage.message_id == message_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar()

    async def count(self, chat_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ChatPinnedMessage)
            .join(Message, Message.id == ChatPinnedMessage.message_id)
            .where(
                ChatPinnedMessage.chat_id == chat_id,
                Message.is_deleted.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def create(self, pin: ChatPinnedMessage) -> None:
        self.session.add(pin)

    async def delete_many(self, chat_id: UUID, message_ids: Sequence[UUID]) -> list[UUID]:
        if not message_ids:
            return []

        stmt = (
            delete(ChatPinnedMessage)
            .where(
                ChatPinnedMessage.chat_id == chat_id,
                ChatPinnedMessage.message_id.in_(list(message_ids)),
            )
            .returning(ChatPinnedMessage.message_id)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_all(self, chat_id: UUID) -> list[UUID]:
        stmt = (
            delete(ChatPinnedMessage)
            .where(ChatPinnedMessage.chat_id == chat_id)
            .returning(ChatPinnedMessage.message_id)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_page(
        self,
        chat_id: UUID,
        limit: int,
        before_seq: int | None = None,
    ) -> list[tuple[ChatPinnedMessage, Message]]:
        conditions = [
            ChatPinnedMessage.chat_id == chat_id,
            Message.is_deleted.is_(False),
        ]
        if before_seq is not None:
            conditions.append(ChatPinnedMessage.message_seq < before_seq)

        stmt = (
            select(ChatPinnedMessage, Message)
            .join(Message, Message.id == ChatPinnedMessage.message_id)
            .where(*conditions)
            .options(*message_load_options())
            .order_by(ChatPinnedMessage.message_seq.desc())
            .limit(limit + 1)
        )
        result = await self.session.execute(stmt)
        return list(result.tuples())
