from uuid import uuid4

import pytest
from faststream.kafka import KafkaBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.models.privacy import ChatUserContact
from app.core.utils import now_utc

OWNER_ID = 101
CONTACT_ID = 202


def contact_message(event_name: str, *, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "event_name": event_name,
        "created_at": now_utc().isoformat(),
        "payload": {
            "owner_id": OWNER_ID,
            "contact_id": CONTACT_ID,
            "source": 1,
            "is_mutual": False,
        },
    }


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestContactsProjectionConsumer:

    async def publish(self, consumer_broker: KafkaBroker, message: dict) -> None:
        await consumer_broker.publish(
            message,
            topic=chat_config.PROFILE_TOPIC,
            headers={"event_name": message["event_name"]},
        )

    async def contacts(self, db_session: AsyncSession) -> set[tuple[int, int]]:
        result = await db_session.execute(select(ChatUserContact))
        return {(item.owner_id, item.contact_id) for item in result.scalars().all()}

    async def test_added_event_builds_projection(
        self, consumer_broker: KafkaBroker, db_session: AsyncSession
    ) -> None:
        await self.publish(consumer_broker, contact_message(chat_config.CONTACT_ADDED_EVENT))

        assert (OWNER_ID, CONTACT_ID) in await self.contacts(db_session)

    async def test_removed_event_drops_the_row(
        self, consumer_broker: KafkaBroker, db_session: AsyncSession
    ) -> None:
        await self.publish(consumer_broker, contact_message(chat_config.CONTACT_ADDED_EVENT))
        await self.publish(consumer_broker, contact_message(chat_config.CONTACT_REMOVED_EVENT))

        assert (OWNER_ID, CONTACT_ID) not in await self.contacts(db_session)

    async def test_duplicate_add_is_idempotent(
        self, consumer_broker: KafkaBroker, db_session: AsyncSession
    ) -> None:
        message = contact_message(chat_config.CONTACT_ADDED_EVENT)
        await self.publish(consumer_broker, message)
        await self.publish(consumer_broker, message)

        assert await self.contacts(db_session) == {(OWNER_ID, CONTACT_ID)}

    async def test_foreign_event_is_ignored(
        self, consumer_broker: KafkaBroker, db_session: AsyncSession
    ) -> None:
        await self.publish(consumer_broker, contact_message("profiles.profile.archived"))

        assert await self.contacts(db_session) == set()
