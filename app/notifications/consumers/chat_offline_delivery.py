import logging
from datetime import datetime
from uuid import UUID

from dishka.integrations.faststream import FromDishka, inject
from faststream.kafka import KafkaRouter
from pydantic import BaseModel

from app.core.consumers.idempotency import EventIdempotencyGuard
from app.core.services.queues.service import QueueService
from app.notifications.config import notification_config
from app.notifications.tasks.push_offline_recipients import PushOfflineRecipientsTask

logger = logging.getLogger(__name__)

router = KafkaRouter()


class OfflineEventDTO(BaseModel):
    event_id: UUID
    event_name: str
    chat_id: UUID
    message_id: UUID
    offline_user_ids: list[int]
    occurred_at: datetime
    sender_id: int | None = None


@router.subscriber(
    notification_config.CHAT_OFFLINE_DELIVERY_TOPIC,
    group_id=notification_config.OFFLINE_PUSH_GROUP_ID,
)
@inject
async def handle_chat_offline_delivery(
    event: OfflineEventDTO,
    queue_service: FromDishka[QueueService],
    idempotency_guard: FromDishka[EventIdempotencyGuard],
) -> None:
    if not await idempotency_guard.try_acquire(
        group=notification_config.OFFLINE_PUSH_GROUP_ID, event_id=event.event_id
    ):
        return

    try:
        await queue_service.push(
            PushOfflineRecipientsTask,
            data={
                "chat_id": str(event.chat_id),
                "message_id": str(event.message_id),
                "sender_id": event.sender_id,
                "offline_user_ids": event.offline_user_ids,
            },
        )
    except Exception:
        await idempotency_guard.release(
            group=notification_config.OFFLINE_PUSH_GROUP_ID, event_id=event.event_id
        )
        raise

    logger.info(
        "Queued offline push fan-out",
        extra={"chat_id": str(event.chat_id), "recipients": len(event.offline_user_ids)},
    )

