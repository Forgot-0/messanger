from dataclasses import dataclass

from app.core.db.repository import PageResult
from app.core.queries import BaseQuery, BaseQueryHandler
from app.notifications.dtos.notifications import NotificationDTO
from app.notifications.filters.notifications import NotificationFilter
from app.notifications.models.notification import Notification
from app.notifications.repositories.notifications import NotificationRepository


@dataclass(frozen=True)
class GetNotificationsQuery(BaseQuery):
    notification_filter: NotificationFilter


@dataclass(frozen=True)
class GetNotificationsQueryHandler(BaseQueryHandler[GetNotificationsQuery, PageResult[NotificationDTO]]):
    notification_repository: NotificationRepository

    async def handle(self, query: GetNotificationsQuery) -> PageResult[NotificationDTO]:
        return await self.notification_repository.cache_paginated(
            NotificationDTO,
            self._handle,
            query=query,
            ttl=90,
        )

    async def _handle(self, query: GetNotificationsQuery) -> PageResult[NotificationDTO]:
        page = await self.notification_repository.find_by_filter(Notification, query.notification_filter)
        return PageResult(
            items=[NotificationDTO.model_validate(item) for item in page.items],
            total=page.total,
            page=page.page,
            page_size=page.page_size,
        )
