from dataclasses import dataclass

from app.core.queries import BaseQuery, BaseQueryHandler
from app.notifications.dtos.notifications import NotificationUnreadCountDTO
from app.notifications.repositories.notifications import NotificationRepository


@dataclass(frozen=True)
class GetUnreadNotificationsCountQuery(BaseQuery):
    user_id: int


@dataclass(frozen=True)
class GetUnreadNotificationsCountQueryHandler(
    BaseQueryHandler[GetUnreadNotificationsCountQuery, NotificationUnreadCountDTO]
):
    notification_repository: NotificationRepository

    async def handle(self, query: GetUnreadNotificationsCountQuery) -> NotificationUnreadCountDTO:
        return await self.notification_repository.cache(
            NotificationUnreadCountDTO,
            self._handle,
            query=query,
            ttl=30,
        )

    async def _handle(self, query: GetUnreadNotificationsCountQuery) -> NotificationUnreadCountDTO:
        unread_count = await self.notification_repository.count_unread(query.user_id)
        return NotificationUnreadCountDTO(unread_count=unread_count)
