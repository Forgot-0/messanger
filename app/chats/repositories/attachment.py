from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, literal, select, tuple_

from app.chats.models.attachment import AttachmentStatus, AttachmentType, MessageAttachment
from app.chats.models.message import Message
from app.core.db.repository import CacheRepository, IRepository


@dataclass
class AttachmentRepository(IRepository[MessageAttachment], CacheRepository):
    _LIST_VERSION_KEY = "chats:attachments:list"

    async def get_by_id(self, attachment_id: UUID) -> MessageAttachment | None:
        result = await self.session.execute(
            select(MessageAttachment).where(MessageAttachment.id == attachment_id)
        )
        return result.scalar()

    async def get_by_ids(self, attachment_ids: list[UUID]) -> list[MessageAttachment]:
        result = await self.session.execute(
            select(MessageAttachment)
            .where(MessageAttachment.id.in_(attachment_ids))
            .order_by(MessageAttachment.created_at)
        )
        return list(result.scalars().all())

    async def create(self, attachment: MessageAttachment) -> None:
        self.session.add(attachment)

    async def get_shared_media_page(
        self,
        chat_id: UUID,
        attachment_types: Sequence[AttachmentType],
        limit: int,
        before: tuple[int, UUID] | None = None,
    ) -> list[tuple[MessageAttachment, Message]]:
        rows: list[tuple[MessageAttachment, Message]] = []
        for attachment_type in dict.fromkeys(attachment_types):
            conditions = [
                MessageAttachment.chat_id == chat_id,
                MessageAttachment.attachment_type == attachment_type,
                MessageAttachment.message_seq.is_not(None),
                MessageAttachment.attachment_status == AttachmentStatus.SUCCESS,
                Message.is_deleted.is_(False),
            ]
            if before is not None:
                before_seq, before_id = before
                conditions.append(
                    tuple_(MessageAttachment.message_seq, MessageAttachment.id)
                    < tuple_(literal(before_seq), literal(before_id))
                )

            stmt = (
                select(MessageAttachment, Message)
                .join(
                    Message,
                    and_(Message.id == MessageAttachment.message_id, Message.chat_id == MessageAttachment.chat_id),
                )
                .where(*conditions)
                .order_by(MessageAttachment.message_seq.desc(), MessageAttachment.id.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            rows.extend(result.tuples())

        rows.sort(key=lambda row: (row[0].message_seq or 0, row[0].id), reverse=True)
        return rows[:limit]
