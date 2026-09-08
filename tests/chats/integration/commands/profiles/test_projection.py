from datetime import timedelta
from uuid import uuid4

import pytest
from dishka import AsyncContainer

from app.chats.commands.profiles.upsert import (
    UpsertProfileProjectionCommand,
    UpsertProfileProjectionCommandHandler,
)
from app.chats.repositories.user_profile import ChatUserProfileRepository
from app.core.utils import now_utc

USER_ID = 8100


@pytest.fixture
async def projection_repository(
    request_container: AsyncContainer,
) -> ChatUserProfileRepository:
    return await request_container.get(ChatUserProfileRepository)


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestUpsertProfileProjection:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> UpsertProfileProjectionCommandHandler:
        return await request_container.get(UpsertProfileProjectionCommandHandler)

    @staticmethod
    def command(**overrides) -> UpsertProfileProjectionCommand:
        payload = {
            "user_id": USER_ID,
            "username": "john",
            "display_name": "John",
            "avatars": {"64": {"jpg": "avatars/8100/64.jpg"}},
            "event_id": uuid4(),
            "event_updated_at": now_utc(),
        }
        payload.update(overrides)
        return UpsertProfileProjectionCommand(**payload)

    async def test_projection_is_created_from_the_event(
        self,
        handler: UpsertProfileProjectionCommandHandler,
        projection_repository: ChatUserProfileRepository,
    ) -> None:
        await handler.handle(self.command())

        stored = await projection_repository.get_by_id(USER_ID)
        assert stored is not None
        assert stored.username == "john"
        assert stored.display_name == "John"
        assert stored.avatar_s3_key == "avatars/8100/64.jpg"

    async def test_newer_event_overwrites_the_projection(
        self,
        handler: UpsertProfileProjectionCommandHandler,
        projection_repository: ChatUserProfileRepository,
    ) -> None:
        base = now_utc()
        await handler.handle(self.command(event_updated_at=base))

        await handler.handle(
            self.command(
                display_name="John the Second",
                event_updated_at=base + timedelta(minutes=1),
            )
        )

        stored = await projection_repository.get_by_id(USER_ID)
        assert stored is not None
        assert stored.display_name == "John the Second"

    async def test_stale_event_does_not_overwrite(
        self,
        handler: UpsertProfileProjectionCommandHandler,
        projection_repository: ChatUserProfileRepository,
    ) -> None:
        base = now_utc()
        await handler.handle(self.command(display_name="Актуальное", event_updated_at=base))

        await handler.handle(
            self.command(
                display_name="Устаревшее",
                event_updated_at=base - timedelta(hours=1),
            )
        )

        stored = await projection_repository.get_by_id(USER_ID)
        assert stored is not None
        assert stored.display_name == "Актуальное"

    async def test_event_with_the_same_timestamp_is_not_applied(
        self,
        handler: UpsertProfileProjectionCommandHandler,
        projection_repository: ChatUserProfileRepository,
    ) -> None:
        base = now_utc()
        await handler.handle(self.command(display_name="Первое", event_updated_at=base))

        await handler.handle(self.command(display_name="Второе", event_updated_at=base))

        stored = await projection_repository.get_by_id(USER_ID)
        assert stored is not None
        assert stored.display_name == "Первое"

    async def test_event_without_a_timestamp_is_skipped(
        self,
        handler: UpsertProfileProjectionCommandHandler,
        projection_repository: ChatUserProfileRepository,
    ) -> None:
        await handler.handle(self.command(event_updated_at=None))

        assert await projection_repository.get_by_id(USER_ID) is None

    async def test_missing_avatars_leave_the_key_empty(
        self,
        handler: UpsertProfileProjectionCommandHandler,
        projection_repository: ChatUserProfileRepository,
    ) -> None:
        await handler.handle(self.command(avatars={}))

        stored = await projection_repository.get_by_id(USER_ID)
        assert stored is not None
        assert stored.avatar_s3_key is None

    async def test_avatar_of_another_size_is_still_picked(
        self,
        handler: UpsertProfileProjectionCommandHandler,
        projection_repository: ChatUserProfileRepository,
    ) -> None:
        await handler.handle(
            self.command(avatars={"128": {"jpg": "avatars/8100/128.jpg"}})
        )

        stored = await projection_repository.get_by_id(USER_ID)
        assert stored is not None
        assert stored.avatar_s3_key == "avatars/8100/128.jpg"

    async def test_projections_of_different_users_do_not_collide(
        self,
        handler: UpsertProfileProjectionCommandHandler,
        projection_repository: ChatUserProfileRepository,
    ) -> None:
        await handler.handle(self.command(username="first"))
        await handler.handle(self.command(user_id=USER_ID + 1, username="second"))

        first = await projection_repository.get_by_id(USER_ID)
        second = await projection_repository.get_by_id(USER_ID + 1)
        assert first is not None and second is not None
        assert (first.username, second.username) == ("first", "second")
