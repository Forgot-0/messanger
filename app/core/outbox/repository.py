from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.configs.app import app_config
from app.core.outbox.model import OutboxMessage
from app.core.utils import now_utc


@dataclass
class OutboxRepository:
    session: AsyncSession

    async def create(self, outbox_message: OutboxMessage) -> None:
        self.session.add(outbox_message)

    async def cleanup_older_than(self, retention_days: int | None = None) -> int:
        threshold = now_utc() - timedelta(
            days=retention_days or app_config.OUTBOX_RETENTION_DAYS
        )
        subquery = (
            select(OutboxMessage.id)
            .where(OutboxMessage.created_at < threshold)
            .order_by(OutboxMessage.id)
            .limit(app_config.OUTBOX_CLEANUP_BATCH_SIZE)
            .scalar_subquery()
        )
        stmt = (
            delete(OutboxMessage)
            .where(OutboxMessage.id.in_(subquery))
            .returning(OutboxMessage.id)
        )

        result = await self.session.execute(stmt)
        deleted = len(result.scalars().all())
        await self.session.commit()
        return deleted
