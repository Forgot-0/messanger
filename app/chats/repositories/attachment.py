from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, literal, or_, select, text, tuple_, update

from app.chats.models.attachment import AttachmentStatus, AttachmentType, HlsStatus, MessageAttachment
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

    async def set_hls_state(self, root_id: UUID, status: HlsStatus, hls_key: str | None) -> None:
        await self.session.execute(
            update(MessageAttachment)
            .where(
                or_(
                    MessageAttachment.id == root_id,
                    MessageAttachment.source_attachment_id == root_id,
                )
            )
            .values(hls_status=status, hls_key=hls_key)
            .execution_options(synchronize_session=False)
        )

    async def find_stale_transcodes(self, older_than: datetime, limit: int) -> list[MessageAttachment]:
        stmt = (
            select(MessageAttachment)
            .where(
                text("message_attachments.hls_status = 'PENDING'"),
                MessageAttachment.source_attachment_id.is_(None),
                MessageAttachment.updated_at < older_than,
            )
            .order_by(MessageAttachment.updated_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def touch(self, attachment_ids: Sequence[UUID]) -> None:
        if not attachment_ids:
            return

        await self.session.execute(
            update(MessageAttachment)
            .where(MessageAttachment.id.in_(list(attachment_ids)))
            .values(updated_at=func.now())
            .execution_options(synchronize_session=False)
        )
