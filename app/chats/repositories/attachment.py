from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.chats.models.attachment import MessageAttachment
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
