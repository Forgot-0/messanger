from dataclasses import dataclass

from sqlalchemy import func, select, update

from app.core.db.repository import CacheRepository, IRepository
from app.notifications.models.notification import Notification


@dataclass
class NotificationRepository(IRepository[Notification], CacheRepository):
    _LIST_VERSION_KEY = "notifications:list"

    async def create(self, notification: Notification) -> None:
        self.session.add(notification)

    async def get_by_id(self, notification_id: int) -> Notification | None:
        result = await self.session.execute(select(Notification).where(Notification.id == notification_id))
        return result.scalar()

    async def count_unread(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
        )
        return result.scalar_one()

    async def mark_all_as_read(self, user_id: int) -> None:
        await self.session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
            .execution_options(synchronize_session=False)
        )

