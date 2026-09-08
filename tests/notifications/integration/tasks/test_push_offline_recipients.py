from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.notifications.config import notification_config
from app.notifications.models.notification import NotificationType
from app.notifications.tasks.push_offline_recipients import PushOfflineRecipientsTask
from tests.mocks import FakePushService

CHAT_ID = str(uuid4())
MESSAGE_ID = str(uuid4())


async def run_task(container: AsyncContainer, **overrides) -> None:
    kwargs = {
        "chat_id": CHAT_ID,
        "message_id": MESSAGE_ID,
        "sender_id": 1,
        "offline_user_ids": [2, 3],
    }
    kwargs.update(overrides)
    await PushOfflineRecipientsTask.run(dishka_container=container, **kwargs) # type: ignore


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestPushOfflineRecipientsTask:

    async def test_every_offline_recipient_gets_a_push(
        self,
        di_container: AsyncContainer,
        mock_push_service: FakePushService,
    ) -> None:
        await run_task(di_container, offline_user_ids=[101, 102, 103])

        assert {n.user_id for n in mock_push_service.pushed} == {101, 102, 103}

    async def test_push_carries_the_chat_context(
        self,
        di_container: AsyncContainer,
        mock_push_service: FakePushService,
    ) -> None:
        await run_task(di_container, offline_user_ids=[104])

        pushed = mock_push_service.pushed[0]
        assert pushed.type == NotificationType.CHAT
        assert pushed.title == notification_config.PUSH_DEFAULT_TITLE
        assert pushed.payload == {
            "chat_id": CHAT_ID,
            "message_id": MESSAGE_ID,
            "sender_id": 1,
        }

    async def test_empty_recipient_list_sends_nothing(
        self,
        di_container: AsyncContainer,
        mock_push_service: FakePushService,
    ) -> None:
        await run_task(di_container, offline_user_ids=[])

        assert mock_push_service.pushed == []

    async def test_failure_for_one_recipient_does_not_stop_the_rest(
        self,
        di_container: AsyncContainer,
        mock_push_service: FakePushService,
    ) -> None:
        failing_user = 106

        original_push = mock_push_service.push

        async def push_or_fail(notification) -> None:
            if notification.user_id == failing_user:
                raise RuntimeError("FCM отклонил токен")
            await original_push(notification=notification)

        mock_push_service.push = push_or_fail  # type: ignore[method-assign]

        await run_task(di_container, offline_user_ids=[105, failing_user, 107])

        assert {n.user_id for n in mock_push_service.pushed} == {105, 107}

    async def test_task_survives_a_large_recipient_list(
        self,
        di_container: AsyncContainer,
        mock_push_service: FakePushService,
    ) -> None:
        recipients = list(range(200, 200 + notification_config.OFFLINE_PUSH_MAX_CONCURRENCY * 3))

        await run_task(di_container, offline_user_ids=recipients)

        assert {n.user_id for n in mock_push_service.pushed} == set(recipients)
