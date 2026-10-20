from datetime import timedelta
from uuid import uuid4

import pytest
from faststream.kafka import KafkaBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.models.privacy import ChatUserPrivacyException
from app.chats.models.profile import ChatUserProfile
from app.privacy.utils import PrivacyRule, PrivacyVisibility
from app.core.utils import now_utc

USER_ID = 77


def privacy_message(
    *,
    rules: dict[str, str] | None = None,
    exceptions: dict[str, dict[str, list[int]]] | None = None,
    created_at: str | None = None,
    event_id: str | None = None,
    event_name: str = chat_config.PRIVACY_UPDATED_EVENT,
) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "event_name": event_name,
        "created_at": created_at or now_utc().isoformat(),
        "payload": {
            "user_id": USER_ID,
            "rules": rules or {rule.value: PrivacyVisibility.EVERYBODY.value for rule in PrivacyRule},
            "exceptions": exceptions or {},
        },
    }


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestPrivacyProjectionConsumer:

    async def publish(self, consumer_broker: KafkaBroker, message: dict) -> None:
        await consumer_broker.publish(
            message,
            topic=chat_config.PROFILE_TOPIC,
            headers={"event_name": message["event_name"]},
        )

    async def projection(self, db_session: AsyncSession) -> ChatUserProfile | None:
        result = await db_session.execute(
            select(ChatUserProfile).where(ChatUserProfile.user_id == USER_ID)
        )
        return result.scalar()

    async def exceptions(self, db_session: AsyncSession) -> list[ChatUserPrivacyException]:
        result = await db_session.execute(
            select(ChatUserPrivacyException)
            .where(ChatUserPrivacyException.owner_id == USER_ID)
            .order_by(ChatUserPrivacyException.rule, ChatUserPrivacyException.target_id)
        )
        return list(result.scalars().all())

    async def test_settings_are_copied_into_the_projection(
        self, consumer_broker: KafkaBroker, db_session: AsyncSession
    ) -> None:
        await self.publish(
            consumer_broker,
            privacy_message(rules={"photo": "contacts", "calls": "nobody"}),
        )

        projection = await self.projection(db_session)
        assert projection is not None
        assert projection.visibility(PrivacyRule.PHOTO) is PrivacyVisibility.CONTACTS
        assert projection.visibility(PrivacyRule.CALLS) is PrivacyVisibility.NOBODY
        # Не присланные оси считаются открытыми
        assert projection.visibility(PrivacyRule.MESSAGES) is PrivacyVisibility.EVERYBODY

    async def test_exceptions_are_replaced_by_the_snapshot(
        self, consumer_broker: KafkaBroker, db_session: AsyncSession
    ) -> None:
        await self.publish(
            consumer_broker,
            privacy_message(exceptions={"photo": {"allow": [5, 6], "deny": [7]}}),
        )
        first = await self.exceptions(db_session)
        assert {(item.target_id, item.allow) for item in first} == {(5, True), (6, True), (7, False)}

        await self.publish(
            consumer_broker,
            privacy_message(
                exceptions={"photo": {"allow": [], "deny": [8]}},
                created_at=(now_utc() + timedelta(minutes=1)).isoformat(),
            ),
        )

        db_session.expire_all()
        second = await self.exceptions(db_session)
        assert {(item.target_id, item.allow) for item in second} == {(8, False)}

    async def test_stale_event_changes_nothing(
        self, consumer_broker: KafkaBroker, db_session: AsyncSession
    ) -> None:
        await self.publish(
            consumer_broker,
            privacy_message(
                rules={"photo": "nobody"},
                exceptions={"photo": {"allow": [9], "deny": []}},
            ),
        )
        await self.publish(
            consumer_broker,
            privacy_message(
                rules={"photo": "everybody"},
                exceptions={"photo": {"allow": [], "deny": [9]}},
                created_at=(now_utc() - timedelta(hours=1)).isoformat(),
            ),
        )

        db_session.expire_all()
        projection = await self.projection(db_session)
        assert projection is not None
        assert projection.visibility(PrivacyRule.PHOTO) is PrivacyVisibility.NOBODY
        assert [(item.target_id, item.allow) for item in await self.exceptions(db_session)] == [(9, True)]

    async def test_duplicate_delivery_is_applied_once(
        self, consumer_broker: KafkaBroker, db_session: AsyncSession
    ) -> None:
        message = privacy_message(rules={"photo": "nobody"})
        await self.publish(consumer_broker, message)

        message["payload"]["rules"] = {"photo": "everybody"}
        await self.publish(consumer_broker, message)

        db_session.expire_all()
        projection = await self.projection(db_session)
        assert projection is not None
        assert projection.visibility(PrivacyRule.PHOTO) is PrivacyVisibility.NOBODY

    async def test_profile_event_does_not_reach_the_privacy_projection(
        self, consumer_broker: KafkaBroker, db_session: AsyncSession
    ) -> None:
        await self.publish(
            consumer_broker,
            {
                "event_id": str(uuid4()),
                "event_name": "profiles.profile.updated",
                "created_at": now_utc().isoformat(),
                "payload": {"user_id": USER_ID, "username": "john", "avatars": {}},
            },
        )

        projection = await self.projection(db_session)
        assert projection is not None
        assert projection.privacy_source_updated_at is None
