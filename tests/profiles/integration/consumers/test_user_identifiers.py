from uuid import uuid4

import pytest
from faststream.kafka import KafkaBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.model import OutboxMessage
from app.core.utils import now_utc
from app.profiles.config import profile_config
from app.profiles.models.contacts import IdentifierKind
from app.profiles.repositories.contacts import ContactIdentifierRepository, ContactRepository
from app.profiles.repositories.profiles import ProfileRepository

NEW_USER_ID = 9150
WAITING_ID = 9151
EMAIL = "verified@example.com"


def verified_user_message(
    event_id: str | None = None, event_name: str = profile_config.USER_VERIFIED_EVENT
) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "event_name": event_name,
        "created_at": now_utc().isoformat(),
        "payload": {"user_id": NEW_USER_ID, "username": "newcomer", "email": EMAIL},
    }


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestUserVerifiedConsumer:

    async def publish(self, consumer_broker: KafkaBroker, message: dict) -> None:
        await consumer_broker.publish(
            message,
            topic=profile_config.USER_TOPIC,
            headers={"event_name": message["event_name"]},
        )

    async def test_profile_is_created_on_verification(
        self,
        consumer_broker: KafkaBroker,
        profile_repository: ProfileRepository,
    ) -> None:
        await self.publish(consumer_broker, verified_user_message())

        profile = await profile_repository.get_by_id(NEW_USER_ID)
        assert profile is not None
        assert profile.username == "newcomer"

    async def test_profile_creation_writes_the_outbox_row(
        self,
        consumer_broker: KafkaBroker,
        db_session: AsyncSession,
    ) -> None:
        await self.publish(consumer_broker, verified_user_message())

        rows = await db_session.execute(
            select(OutboxMessage).where(
                OutboxMessage.event_name == "profiles.profile.created",
                OutboxMessage.aggregate_id == str(NEW_USER_ID),
            )
        )
        assert rows.scalar() is not None

    async def test_existing_profile_is_not_duplicated(
        self,
        consumer_broker: KafkaBroker,
        make_profile,
        profile_repository: ProfileRepository,
    ) -> None:
        await make_profile(NEW_USER_ID, "already_here", "Уже тут")

        await self.publish(consumer_broker, verified_user_message())

        profile = await profile_repository.get_by_id(NEW_USER_ID)
        assert profile is not None
        assert profile.display_name == "Уже тут"

    async def test_verified_user_gets_an_identifier(
        self,
        consumer_broker: KafkaBroker,
        identifier_repository: ContactIdentifierRepository,
        identifier_hasher,
    ) -> None:
        await self.publish(consumer_broker, verified_user_message())

        identifier_hash = identifier_hasher.hash(IdentifierKind.EMAIL, EMAIL)
        assert await identifier_repository.resolve([identifier_hash]) == {
            identifier_hash: NEW_USER_ID
        }

    async def test_pending_contacts_are_resolved(
        self,
        consumer_broker: KafkaBroker,
        make_pending,
        contact_repository: ContactRepository,
    ) -> None:
        await make_pending(WAITING_ID, EMAIL, first_name="Новичок")

        await self.publish(consumer_broker, verified_user_message())

        contact = await contact_repository.get(WAITING_ID, NEW_USER_ID)
        assert contact is not None
        assert contact.first_name == "Новичок"

    async def test_duplicate_delivery_is_ignored(
        self,
        consumer_broker: KafkaBroker,
        make_pending,
        contact_repository: ContactRepository,
    ) -> None:
        await make_pending(WAITING_ID, EMAIL)
        message = verified_user_message()

        await self.publish(consumer_broker, message)
        await self.publish(consumer_broker, message)

        assert await contact_repository.count(WAITING_ID) == 1

    async def test_other_event_of_the_topic_is_ignored(
        self,
        consumer_broker: KafkaBroker,
        identifier_repository: ContactIdentifierRepository,
        identifier_hasher,
        profile_repository: ProfileRepository,
    ) -> None:
        await self.publish(
            consumer_broker, verified_user_message(event_name="auth.session.created")
        )

        identifier_hash = identifier_hasher.hash(IdentifierKind.EMAIL, EMAIL)
        assert await identifier_repository.resolve([identifier_hash]) == {}
        assert await profile_repository.get_by_id(NEW_USER_ID) is None
