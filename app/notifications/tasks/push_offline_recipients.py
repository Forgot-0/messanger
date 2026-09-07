import asyncio
import logging
from dataclasses import dataclass

from dishka.integrations.taskiq import FromDishka, inject

from app.core.mediators.base import BaseMediator
from app.core.services.queues.task import BaseTask
from app.notifications.commands.notifications.push import PushNotificationCommand
from app.notifications.config import notification_config
from app.notifications.models.notification import NotificationType

logger = logging.getLogger(__name__)


@dataclass
class PushOfflineRecipientsTask(BaseTask):
    __task_name__ = "notifications.push.offline_recipients"

    @staticmethod
    @inject
    async def run(
        chat_id: str,
        message_id: str | None,
        sender_id: int | None,
        offline_user_ids: list[int],
        mediator: FromDishka[BaseMediator],
    ) -> None:
        if not offline_user_ids:
            return

        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "sender_id": sender_id,
        }

        semaphore = asyncio.Semaphore(notification_config.OFFLINE_PUSH_MAX_CONCURRENCY)

        async def push_one(user_id: int) -> None:
            async with semaphore:
                try:
                    await mediator.handle_command(
                        PushNotificationCommand(
                            user_id=user_id,
                            title=notification_config.PUSH_DEFAULT_TITLE,
                            type=NotificationType.CHAT,
                            message=None,
                            payload=payload,
                        )
                    )
                except Exception:
                    logger.exception(
                        "Failed to push offline notification",
                        extra={"user_id": user_id, "chat_id": chat_id},
                    )

        await asyncio.gather(*(push_one(user_id) for user_id in offline_user_ids))

