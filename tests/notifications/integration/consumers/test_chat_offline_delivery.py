from uuid import uuid4

import pytest
from faststream.kafka import KafkaBroker

from app.core.utils import now_utc
from app.notifications.config import notification_config
from app.notifications.tasks.push_offline_recipients import PushOfflineRecipientsTask
from tests.mocks import FakeQueueService

CHAT_ID = uuid4()
MESSAGE_ID = uuid4()


def offline_message(
    *,
    offline_user_ids: list[int] | None = None,
    event_id: str | None = None,
) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "event_name": "chats.message.sent",
        "chat_id": str(CHAT_ID),
        "message_id": str(MESSAGE_ID),
        "sender_id": 1,
        "offline_user_ids": offline_user_ids if offline_user_ids is not None else [2, 3],
        "occurred_at": now_utc().isoformat(),
    }


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestChatOfflineDeliveryConsumer:
    async def publish(self, consumer_broker: KafkaBroker, message: dict) -> None:
        await consumer_broker.publish(
            message,
            topic=notification_config.CHAT_OFFLINE_DELIVERY_TOPIC,
        )

    async def test_offline_signal_queues_push_task(
        self,
        consumer_broker: KafkaBroker,
        mock_queue_service: FakeQueueService,
    ) -> None:
        await self.publish(consumer_broker, offline_message())

        assert len(mock_queue_service.pushed) == 1
        task, data = mock_queue_service.pushed[0]
        assert task is PushOfflineRecipientsTask
        assert data == {
            "chat_id": str(CHAT_ID),
            "message_id": str(MESSAGE_ID),
            "sender_id": 1,
            "offline_user_ids": [2, 3],
        }

    async def test_duplicate_delivery_queues_one_task(
        self,
        consumer_broker: KafkaBroker,
        mock_queue_service: FakeQueueService,
    ) -> None:
        message = offline_message()

        await self.publish(consumer_broker, message)
        await self.publish(consumer_broker, message)

        assert len(mock_queue_service.pushed) == 1

    async def test_signal_without_recipients_still_queues_task(
        self,
        consumer_broker: KafkaBroker,
        mock_queue_service: FakeQueueService,
    ) -> None:
        await self.publish(consumer_broker, offline_message(offline_user_ids=[]))

        assert len(mock_queue_service.pushed) == 1
        _task, data = mock_queue_service.pushed[0]
        assert data["offline_user_ids"] == []
