from collections.abc import Callable

import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models.notification import Notification, NotificationType
from app.notifications.repositories.devices import DeviceRepository
from app.notifications.repositories.notifications import NotificationRepository


@pytest.fixture
async def notification_repository(request_container: AsyncContainer) -> NotificationRepository:
    return await request_container.get(NotificationRepository)


@pytest.fixture
async def device_repository(request_container: AsyncContainer) -> DeviceRepository:
    return await request_container.get(DeviceRepository)


@pytest.fixture
def make_notification() -> Callable[..., Notification]:
    def _make(
        *,
        user_id: int = 1,
        type: NotificationType = NotificationType.SYSTEM,
        title: str = "Заголовок",
        message: str | None = "Текст",
        payload: dict | None = None,
        is_read: bool = False,
    ) -> Notification:
        notification = Notification.create(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            payload=payload if payload is not None else {},
        )
        notification.is_read = is_read
        return notification

    return _make


@pytest.fixture
async def persist_notifications(
    db_session: AsyncSession,
    make_notification: Callable[..., Notification],
):
    async def _persist(count: int = 1, **kwargs) -> list[Notification]:
        created = [
            make_notification(title=f"Уведомление {i}", **kwargs)
            for i in range(count)
        ]
        db_session.add_all(created)
        await db_session.commit()
        return created

    return _persist
