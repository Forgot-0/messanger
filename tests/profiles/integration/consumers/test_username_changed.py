from uuid import uuid4

import pytest
from faststream.kafka import KafkaBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.model import OutboxMessage
from app.core.utils import now_utc
from app.profiles.config import profile_config
from app.profiles.repositories.profiles import ProfileRepository

USER_ID = 9250


def username_changed_message(username: str, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "event_name": profile_config.USERNAME_CHANGED_EVENT,
        "created_at": now_utc().isoformat(),
        "payload": {"user_id": USER_ID, "old_username": "old_name", "username": username},
    }


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestUsernameChangedConsumer:

    async def publish(self, consumer_broker: KafkaBroker, message: dict) -> None:
        await consumer_broker.publish(
            message,
            topic=profile_config.USER_TOPIC,
            headers={"event_name": message["event_name"]},
        )

    async def test_profile_takes_the_new_username(
        self,
        consumer_broker: KafkaBroker,
        make_profile,
        profile_repository: ProfileRepository,
        db_session: AsyncSession,
    ) -> None:
        await make_profile(USER_ID, "old_name", "Тот же человек")

        await self.publish(consumer_broker, username_changed_message("New_Name"))

        profile = await profile_repository.get_by_id(USER_ID)
        assert profile is not None
        assert profile.username == "New_Name"
        assert profile.display_name == "Тот же человек"

        # Проекция чатов узнаёт об имени из обычного profiles.profile.updated
        row = (
            await db_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_name == "profiles.profile.updated",
                    OutboxMessage.aggregate_id == str(USER_ID),
                )
            )
        ).scalar_one()
        assert row.payload["username"] == "New_Name"

    async def test_lookup_by_the_new_username_ignores_case(
        self,
        consumer_broker: KafkaBroker,
        make_profile,
        profile_repository: ProfileRepository,
    ) -> None:
        await make_profile(USER_ID, "old_name")

        await self.publish(consumer_broker, username_changed_message("New_Name"))

        found = await profile_repository.get_by_username("new_name")
        assert found is not None and found.id == USER_ID
        assert await profile_repository.get_by_username("old_name") is None

    async def test_missing_profile_is_created_with_the_new_username(
        self,
        consumer_broker: KafkaBroker,
        profile_repository: ProfileRepository,
    ) -> None:
        await self.publish(consumer_broker, username_changed_message("early_bird"))

        profile = await profile_repository.get_by_id(USER_ID)
        assert profile is not None and profile.username == "early_bird"

    async def test_verification_after_the_change_keeps_the_new_name(
        self,
        consumer_broker: KafkaBroker,
        profile_repository: ProfileRepository,
    ) -> None:
        await self.publish(consumer_broker, username_changed_message("early_bird"))
        await self.publish(
            consumer_broker,
            {
                "event_id": str(uuid4()),
                "event_name": profile_config.USER_VERIFIED_EVENT,
                "created_at": now_utc().isoformat(),
                "payload": {"user_id": USER_ID, "username": "old_name", "email": "bird@example.com"},
            },
        )

        profile = await profile_repository.get_by_id(USER_ID)
        assert profile is not None and profile.username == "early_bird"

    async def test_duplicate_delivery_is_applied_once(
        self,
        consumer_broker: KafkaBroker,
        make_profile,
        db_session: AsyncSession,
    ) -> None:
        await make_profile(USER_ID, "old_name")
        message = username_changed_message("New_Name")

        await self.publish(consumer_broker, message)
        await self.publish(consumer_broker, message)

        rows = await db_session.execute(
            select(OutboxMessage).where(
                OutboxMessage.event_name == "profiles.profile.updated",
                OutboxMessage.aggregate_id == str(USER_ID),
            )
        )
        assert len(rows.scalars().all()) == 1

    async def test_foreign_auth_events_are_ignored(
        self,
        consumer_broker: KafkaBroker,
        make_profile,
        profile_repository: ProfileRepository,
    ) -> None:
        await make_profile(USER_ID, "old_name")
        message = username_changed_message("New_Name")
        message["event_name"] = "auth.session.created"

        await self.publish(consumer_broker, message)

        profile = await profile_repository.get_by_id(USER_ID)
        assert profile is not None and profile.username == "old_name"
