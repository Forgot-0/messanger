import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.notifications.models.notification import Notification, NotificationType
from app.notifications.repositories.notifications import NotificationRepository
from app.notifications.services.push.base import PushService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PushNotificationCommand(BaseCommand):
    user_id: int
    title: str
    type: NotificationType
    message: str | None
    payload: dict


@dataclass(frozen=True)
class PushNotificationCommandHandler(BaseCommandHandler[PushNotificationCommand, None]):
    session: AsyncSession
    push_service: PushService
    notification_repository: NotificationRepository

    async def handle(self, command: PushNotificationCommand) -> None:
        notification = Notification.create(
            user_id=command.user_id,
            type=command.type,
            title=command.title,
            message=command.message,
            payload=command.payload
        )
        await self.notification_repository.create(notification)
        await self.push_service.push(notification=notification)

        await self.session.commit()
        logger.info(
            "Push notification",
            extra={"user_id": command.user_id},
        )

