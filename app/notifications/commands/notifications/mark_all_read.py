import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData
from app.notifications.repositories.notifications import NotificationRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarkAllNotificationsAsReadCommand(BaseCommand):
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class MarkAllNotificationsAsReadCommandHandler(BaseCommandHandler[MarkAllNotificationsAsReadCommand, int]):
    session: AsyncSession
    notification_repository: NotificationRepository

    async def handle(self, command: MarkAllNotificationsAsReadCommand) -> None:
        await self.notification_repository.mark_all_as_read(int(command.user_jwt_data.id))
        await self.notification_repository.invalidate_cache()
        await self.session.commit()
        logger.info(
            "Mark all notifications as read",
            extra={"user_id": command.user_jwt_data.id},
        )
