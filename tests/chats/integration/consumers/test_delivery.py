from uuid import uuid4

import pytest
from faststream.kafka import KafkaBroker

from app.chats.config import chat_config
from app.chats.models.chat import Chat
from app.core.utils import now_utc


def chat_message(event_name: str, payload: dict, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "event_name": event_name,
        "created_at": now_utc().isoformat(),
        "payload": payload,
    }


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatDeliveryConsumer:
    async def publish(self, consumer_broker: KafkaBroker, message: dict) -> None:
        await consumer_broker.publish(
            message,
            topic=chat_config.CHAT_TOPIC,
            headers={"event_name": message["event_name"]},
        )

    async def test_read_event_is_delivered_to_online_member(
        self,
        consumer_broker: KafkaBroker,
        group_chat: Chat,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(2)

        message = chat_message(
            "chats.message.readed",
            {"chat_id": str(group_chat.id), "seq": 17, "reader_id": 3},
        )
        await self.publish(consumer_broker, message)

        frames = await delivered_frames()
        assert len(frames) == 1
        assert frames[0]["type"] == "messages_read"
        assert frames[0]["channel"] == str(group_chat.id)
        assert frames[0]["payload"]["event_id"] == message["event_id"]

    async def test_duplicate_delivery_is_routed_once(
        self,
        consumer_broker: KafkaBroker,
        group_chat: Chat,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(2)

        message = chat_message(
            "chats.message.readed",
            {"chat_id": str(group_chat.id), "seq": 17, "reader_id": 3},
        )
        await self.publish(consumer_broker, message)
        await self.publish(consumer_broker, message)

        assert len(await delivered_frames()) == 1

    async def test_unknown_event_name_is_ignored(
        self,
        consumer_broker: KafkaBroker,
        group_chat: Chat,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(2)

        await self.publish(
            consumer_broker,
            chat_message("chats.message.unknown", {"chat_id": str(group_chat.id)}),
        )

        assert await delivered_frames() == []

    async def test_event_for_missing_chat_is_ignored(
        self,
        consumer_broker: KafkaBroker,
        go_online,
        delivered_frames,
    ) -> None:
        await go_online(2)

        await self.publish(
            consumer_broker,
            chat_message(
                "chats.message.readed",
                {"chat_id": str(uuid4()), "seq": 1, "reader_id": 3},
            ),
        )

        assert await delivered_frames() == []
