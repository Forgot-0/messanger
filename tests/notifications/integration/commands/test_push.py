import pytest
from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.commands.notifications.push import (
    PushNotificationCommand,
    PushNotificationCommandHandler,
)
from app.notifications.models.notification import Notification, NotificationType
from app.notifications.repositories.notifications import NotificationRepository
from tests.mocks import FakePushService


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestPushNotificationCommand:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> PushNotificationCommandHandler:
        return await request_container.get(PushNotificationCommandHandler)

    @staticmethod
    def command(**overrides) -> PushNotificationCommand:
        payload = {
            "user_id": 4242,
            "type": NotificationType.CHAT,
            "title": "Новое сообщение",
            "message": "Текст",
            "payload": {"chat_id": "c-1"},
        }
        payload.update(overrides)
        return PushNotificationCommand(**payload)

    async def test_notification_is_stored_with_command_fields(
        self,
        handler: PushNotificationCommandHandler,
        db_session: AsyncSession,
    ) -> None:
        await handler.handle(self.command())

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == 4242)
        )
        stored = result.scalars().one()

        assert stored.type == NotificationType.CHAT
        assert stored.title == "Новое сообщение"
        assert stored.message == "Текст"
        assert stored.payload == {"chat_id": "c-1"}
        assert stored.is_read is False

    async def test_push_service_receives_that_notification(
        self,
        handler: PushNotificationCommandHandler,
        mock_push_service: FakePushService,
    ) -> None:
        await handler.handle(self.command(user_id=4243))

        assert len(mock_push_service.pushed) == 1
        pushed = mock_push_service.pushed[0]
        assert pushed.user_id == 4243
        assert pushed.title == "Новое сообщение"

    async def test_notification_without_message_is_allowed(
        self,
        handler: PushNotificationCommandHandler,
        mock_push_service: FakePushService,
    ) -> None:
        await handler.handle(self.command(user_id=4244, message=None))

        assert mock_push_service.pushed[0].message is None

    async def test_each_command_produces_one_push(
        self,
        handler: PushNotificationCommandHandler,
        mock_push_service: FakePushService,
        notification_repository: NotificationRepository,
    ) -> None:
        for _ in range(3):
            await handler.handle(self.command(user_id=4245))

        assert len(mock_push_service.pushed) == 3
        assert await notification_repository.count_unread(4245) == 3

    async def test_notification_survives_a_failed_delivery(
        self,
        handler: PushNotificationCommandHandler,
        mock_push_service: FakePushService,
        db_session: AsyncSession,
    ) -> None:
        mock_push_service.fail_with = RuntimeError("FCM недоступен")

        with pytest.raises(RuntimeError):
            await handler.handle(self.command(user_id=4246))

        assert mock_push_service.pushed == []
        result = await db_session.execute(
            select(Notification).where(Notification.user_id == 4246)
        )
        stored = result.scalars().one()
        assert stored.is_read is False
