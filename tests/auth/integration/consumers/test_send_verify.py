from uuid import uuid4

import pytest
from faststream.kafka import KafkaBroker

from app.auth.config import auth_config
from app.auth.models.user import CreatedUserEvent, User
from app.auth.repositories.session import TokenBlacklistRepository
from app.core.utils import now_utc
from tests.mocks import MockMailService


def created_user_message(user: User, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "event_name": CreatedUserEvent.get_name(),
        "created_at": now_utc().isoformat(),
        "payload": {"email": user.email, "username": user.username},
    }


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestSendVerifyConsumer:
    async def publish(self, consumer_broker: KafkaBroker, message: dict) -> None:
        await consumer_broker.publish(
            message,
            topic=auth_config.USER_TOPIC,
            headers={"event_name": message["event_name"]},
        )

    async def test_created_user_event_queues_verify_email(
        self,
        consumer_broker: KafkaBroker,
        standard_user: User,
        mock_mail_service: MockMailService,
    ) -> None:
        await self.publish(consumer_broker, created_user_message(standard_user))

        assert len(mock_mail_service.sent_emails) == 1
        sent = mock_mail_service.sent_emails[0]
        assert sent["data"].recipient == standard_user.email
        assert sent["template"].token

    async def test_token_is_stored_for_verification(
        self,
        consumer_broker: KafkaBroker,
        standard_user: User,
        mock_mail_service: MockMailService,
        token_blacklist_repository: TokenBlacklistRepository,
    ) -> None:
        await self.publish(consumer_broker, created_user_message(standard_user))

        token = mock_mail_service.sent_emails[0]["template"].token
        assert await token_blacklist_repository.is_valid_token(token) == standard_user.id

    async def test_duplicate_delivery_sends_one_email(
        self,
        consumer_broker: KafkaBroker,
        standard_user: User,
        mock_mail_service: MockMailService,
    ) -> None:
        message = created_user_message(standard_user)

        await self.publish(consumer_broker, message)
        await self.publish(consumer_broker, message)

        assert len(mock_mail_service.sent_emails) == 1

    async def test_other_event_in_topic_is_ignored(
        self,
        consumer_broker: KafkaBroker,
        standard_user: User,
        mock_mail_service: MockMailService,
    ) -> None:
        message = created_user_message(standard_user)
        message["event_name"] = "auth.user.verified"

        await self.publish(consumer_broker, message)

        assert mock_mail_service.sent_emails == []
