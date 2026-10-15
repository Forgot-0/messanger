from uuid import uuid4

import pytest
from faststream.kafka import KafkaBroker
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.repositories.blocks import ChatUserBlockRepository
from app.core.utils import now_utc


def block_message(event_name: str, owner_id: int = 10, target_id: int = 20, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "event_name": event_name,
        "created_at": now_utc().isoformat(),
        "payload": {"owner_id": owner_id, "target_id": target_id},
    }


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestBlockProjectionConsumer:
    @pytest.fixture
    def block_repository(self, db_session: AsyncSession) -> ChatUserBlockRepository:
        return ChatUserBlockRepository(session=db_session)

    async def publish(self, consumer_broker: KafkaBroker, message: dict) -> None:
        await consumer_broker.publish(
            message,
            topic=chat_config.PROFILE_TOPIC,
            headers={"event_name": message["event_name"]},
        )

    async def test_blocked_event_creates_projection_row(
        self, consumer_broker: KafkaBroker, block_repository: ChatUserBlockRepository
    ) -> None:
        await self.publish(consumer_broker, block_message(chat_config.USER_BLOCKED_EVENT))

        assert await block_repository.blockers_of(20, [10]) == {10}
        assert await block_repository.is_blocked_between(20, 10) is True

    async def test_unblocked_event_removes_row(
        self, consumer_broker: KafkaBroker, block_repository: ChatUserBlockRepository
    ) -> None:
        await self.publish(consumer_broker, block_message(chat_config.USER_BLOCKED_EVENT))
        await self.publish(consumer_broker, block_message(chat_config.USER_UNBLOCKED_EVENT))

        assert await block_repository.blockers_of(20, [10]) == set()

    async def test_duplicate_delivery_is_idempotent(
        self, consumer_broker: KafkaBroker, block_repository: ChatUserBlockRepository
    ) -> None:
        message = block_message(chat_config.USER_BLOCKED_EVENT)
        await self.publish(consumer_broker, message)
        await self.publish(consumer_broker, block_message(chat_config.USER_UNBLOCKED_EVENT))
        await self.publish(consumer_broker, message)

        assert await block_repository.blockers_of(20, [10]) == set()

    async def test_other_profile_events_are_ignored(
        self, consumer_broker: KafkaBroker, block_repository: ChatUserBlockRepository
    ) -> None:
        await self.publish(consumer_broker, {
            "event_id": str(uuid4()),
            "event_name": "profiles.contact.added",
            "created_at": now_utc().isoformat(),
            "payload": {"owner_id": 10, "contact_id": 20, "source": 4, "is_mutual": False},
        })

        assert await block_repository.blockers_of(20, [10]) == set()
