import pytest
from dishka import AsyncContainer
from redis.asyncio import Redis

from app.core.services.auth.dto import UserJWTData
from app.notifications.commands.notifications.mark_all_read import (
    MarkAllNotificationsAsReadCommand,
    MarkAllNotificationsAsReadCommandHandler,
)
from app.notifications.commands.notifications.mark_read import (
    MarkNotificationAsReadCommand,
    MarkNotificationAsReadCommandHandler,
)
from app.notifications.exceptions import NotFoundNotificationError, NotificationAccessDeniedError
from app.notifications.repositories.notifications import NotificationRepository


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestMarkNotificationAsReadCommand:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> MarkNotificationAsReadCommandHandler:
        return await request_container.get(MarkNotificationAsReadCommandHandler)

    async def test_owner_marks_own_notification_as_read(
        self,
        handler: MarkNotificationAsReadCommandHandler,
        notification_repository: NotificationRepository,
        persist_notifications,
        user_jwt: UserJWTData,
    ) -> None:
        (notification,) = await persist_notifications(1, user_id=int(user_jwt.id))

        await handler.handle(
            MarkNotificationAsReadCommand(
                notification_id=notification.id,
                is_read=True,
                user_jwt_data=user_jwt,
            )
        )

        stored = await notification_repository.get_by_id(notification.id)
        assert stored is not None
        assert stored.is_read is True

    async def test_read_flag_can_be_unset(
        self,
        handler: MarkNotificationAsReadCommandHandler,
        notification_repository: NotificationRepository,
        persist_notifications,
        user_jwt: UserJWTData,
    ) -> None:
        (notification,) = await persist_notifications(
            1, user_id=int(user_jwt.id), is_read=True
        )

        await handler.handle(
            MarkNotificationAsReadCommand(
                notification_id=notification.id,
                is_read=False,
                user_jwt_data=user_jwt,
            )
        )

        stored = await notification_repository.get_by_id(notification.id)
        assert stored is not None
        assert stored.is_read is False

    async def test_marking_twice_is_idempotent(
        self,
        handler: MarkNotificationAsReadCommandHandler,
        notification_repository: NotificationRepository,
        persist_notifications,
        user_jwt: UserJWTData,
    ) -> None:
        (notification,) = await persist_notifications(1, user_id=int(user_jwt.id))
        command = MarkNotificationAsReadCommand(
            notification_id=notification.id,
            is_read=True,
            user_jwt_data=user_jwt,
        )

        await handler.handle(command)
        await handler.handle(command)

        stored = await notification_repository.get_by_id(notification.id)
        assert stored is not None
        assert stored.is_read is True

    async def test_foreign_notification_is_denied(
        self,
        handler: MarkNotificationAsReadCommandHandler,
        notification_repository: NotificationRepository,
        persist_notifications,
        make_user_jwt,
    ) -> None:
        (notification,) = await persist_notifications(1, user_id=777)
        stranger = make_user_jwt(id="778")

        with pytest.raises(NotificationAccessDeniedError):
            await handler.handle(
                MarkNotificationAsReadCommand(
                    notification_id=notification.id,
                    is_read=True,
                    user_jwt_data=stranger,
                )
            )

        untouched = await notification_repository.get_by_id(notification.id)
        assert untouched is not None
        assert untouched.is_read is False

    async def test_missing_notification_raises(
        self,
        handler: MarkNotificationAsReadCommandHandler,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundNotificationError):
            await handler.handle(
                MarkNotificationAsReadCommand(
                    notification_id=9_999_999,
                    is_read=True,
                    user_jwt_data=user_jwt,
                )
            )

    async def test_cache_is_invalidated_after_the_commit(
        self,
        handler: MarkNotificationAsReadCommandHandler,
        notification_repository: NotificationRepository,
        persist_notifications,
        user_jwt: UserJWTData,
        redis_client: Redis,
    ) -> None:
        (notification,) = await persist_notifications(1, user_id=int(user_jwt.id))
        version_key = NotificationRepository._LIST_VERSION_KEY
        await redis_client.set(version_key, 5)

        await handler.handle(
            MarkNotificationAsReadCommand(
                notification_id=notification.id,
                is_read=True,
                user_jwt_data=user_jwt,
            )
        )
        version = await redis_client.get(version_key)
        assert version is not None
        assert int(version) == 6
        stored = await notification_repository.get_by_id(notification.id)
        assert stored is not None and stored.is_read is True


@pytest.mark.integration
@pytest.mark.notifications
@pytest.mark.asyncio
class TestMarkAllNotificationsAsReadCommand:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> MarkAllNotificationsAsReadCommandHandler:
        return await request_container.get(MarkAllNotificationsAsReadCommandHandler)

    async def test_all_own_notifications_become_read(
        self,
        handler: MarkAllNotificationsAsReadCommandHandler,
        notification_repository: NotificationRepository,
        persist_notifications,
        user_jwt: UserJWTData,
    ) -> None:
        await persist_notifications(3, user_id=int(user_jwt.id))

        await handler.handle(MarkAllNotificationsAsReadCommand(user_jwt_data=user_jwt))

        assert await notification_repository.count_unread(int(user_jwt.id)) == 0

    async def test_other_users_notifications_are_untouched(
        self,
        handler: MarkAllNotificationsAsReadCommandHandler,
        notification_repository: NotificationRepository,
        persist_notifications,
        user_jwt: UserJWTData,
    ) -> None:
        await persist_notifications(2, user_id=int(user_jwt.id))
        await persist_notifications(2, user_id=888)

        await handler.handle(MarkAllNotificationsAsReadCommand(user_jwt_data=user_jwt))

        assert await notification_repository.count_unread(int(user_jwt.id)) == 0
        assert await notification_repository.count_unread(888) == 2

    async def test_second_call_is_a_noop(
        self,
        handler: MarkAllNotificationsAsReadCommandHandler,
        notification_repository: NotificationRepository,
        persist_notifications,
        user_jwt: UserJWTData,
    ) -> None:
        await persist_notifications(2, user_id=int(user_jwt.id))
        command = MarkAllNotificationsAsReadCommand(user_jwt_data=user_jwt)

        await handler.handle(command)
        await handler.handle(command)

        assert await notification_repository.count_unread(int(user_jwt.id)) == 0

    async def test_user_without_notifications_does_not_fail(
        self,
        handler: MarkAllNotificationsAsReadCommandHandler,
        notification_repository: NotificationRepository,
        make_user_jwt,
    ) -> None:
        empty_user = make_user_jwt(id="999")

        await handler.handle(MarkAllNotificationsAsReadCommand(user_jwt_data=empty_user))

        assert await notification_repository.count_unread(999) == 0

    async def test_cache_is_invalidated_after_the_commit(
        self,
        handler: MarkAllNotificationsAsReadCommandHandler,
        persist_notifications,
        user_jwt: UserJWTData,
        redis_client: Redis,
        notification_repository: NotificationRepository,
    ) -> None:
        await persist_notifications(2, user_id=int(user_jwt.id))
        version_key = NotificationRepository._LIST_VERSION_KEY
        await redis_client.set(version_key, 1)

        await handler.handle(MarkAllNotificationsAsReadCommand(user_jwt_data=user_jwt))

        version = await redis_client.get(version_key)
        assert version is not None
        assert int(version) == 2
        assert await notification_repository.count_unread(int(user_jwt.id)) == 0
