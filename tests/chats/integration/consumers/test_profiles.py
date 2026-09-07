from datetime import timedelta
from uuid import uuid4

import pytest
from faststream.exceptions import SubscriberNotFound
from faststream.kafka import KafkaBroker
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.repositories.user_profile import ChatUserProfileRepository
from app.core.utils import now_utc

USER_ID = 42
AVATARS = {"64": {"jpg": "avatars/42/64.jpg"}}


def profile_message(
    event_name: str = "profiles.profile.created",
    *,
    username: str = "john",
    display_name: str | None = "John",
    created_at: str | None = None,
    event_id: str | None = None,
) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "event_name": event_name,
        "created_at": created_at or now_utc().isoformat(),
        "payload": {
            "user_id": USER_ID,
            "username": username,
            "display_name": display_name,
            "avatars": AVATARS,
        },
    }


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestProfileProjectionConsumer:
    @pytest.fixture
    def profile_projection_repository(
        self, redis_client: Redis, db_session: AsyncSession
    ) -> ChatUserProfileRepository:
        return ChatUserProfileRepository(redis=redis_client, session=db_session)

    async def publish(self, consumer_broker: KafkaBroker, message: dict) -> None:
        await consumer_broker.publish(
            message,
            topic=chat_config.PROFILE_TOPIC,
            headers={"event_name": message["event_name"]},
        )

    async def test_created_event_builds_projection(
        self,
        consumer_broker: KafkaBroker,
        profile_projection_repository: ChatUserProfileRepository,
    ) -> None:
        await self.publish(consumer_broker, profile_message())

        projection = await profile_projection_repository.get_by_id(USER_ID)
        assert projection is not None
        assert projection.username == "john"
        assert projection.display_name == "John"
        assert projection.avatar_s3_key == "avatars/42/64.jpg"

    async def test_updated_event_overwrites_projection(
        self,
        consumer_broker: KafkaBroker,
        profile_projection_repository: ChatUserProfileRepository,
    ) -> None:
        await self.publish(consumer_broker, profile_message())
        await self.publish(
            consumer_broker,
            profile_message(
                "profiles.profile.updated",
                display_name="John the Second",
                created_at=(now_utc() + timedelta(minutes=1)).isoformat(),
            ),
        )

        projection = await profile_projection_repository.get_by_id(USER_ID)
        assert projection is not None
        assert projection.display_name == "John the Second"

    async def test_stale_event_does_not_overwrite_newer_projection(
        self,
        consumer_broker: KafkaBroker,
        profile_projection_repository: ChatUserProfileRepository,
    ) -> None:
        await self.publish(consumer_broker, profile_message(display_name="Actual"))
        await self.publish(
            consumer_broker,
            profile_message(
                "profiles.profile.updated",
                display_name="Stale",
                created_at=(now_utc() - timedelta(hours=1)).isoformat(),
            ),
        )

        projection = await profile_projection_repository.get_by_id(USER_ID)
        assert projection is not None
        assert projection.display_name == "Actual"

    async def test_duplicate_delivery_is_applied_once(
        self,
        consumer_broker: KafkaBroker,
        profile_projection_repository: ChatUserProfileRepository,
    ) -> None:
        message = profile_message(display_name="First")
        await self.publish(consumer_broker, message)

        message["payload"]["display_name"] = "Second"
        await self.publish(consumer_broker, message)

        projection = await profile_projection_repository.get_by_id(USER_ID)
        assert projection is not None
        assert projection.display_name == "First"

    async def test_foreign_event_does_not_touch_projection(
        self,
        consumer_broker: KafkaBroker,
        profile_projection_repository: ChatUserProfileRepository,
    ) -> None:
        # Подписчик отбирает события фильтром по заголовку. В проде не подошедшее
        # сообщение FastStream логирует как SubscriberNotFound и пропускает,
        # в TestKafkaBroker — пробрасывает наружу.
        with pytest.raises(SubscriberNotFound):
            await self.publish(consumer_broker, profile_message("profiles.profile.deleted"))

        assert await profile_projection_repository.get_by_id(USER_ID) is None
