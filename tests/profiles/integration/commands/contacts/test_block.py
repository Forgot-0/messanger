import pytest
from dishka import AsyncContainer

from app.core.services.auth.dto import UserJWTData
from app.profiles.commands.contacts.block import BlockUserCommand, BlockUserCommandHandler
from app.profiles.commands.contacts.unblock import UnblockUserCommand, UnblockUserCommandHandler
from app.profiles.exceptions import SelfContactError
from app.profiles.keys import ContactKeys
from app.profiles.models.contacts import UserBlocked, UserUnblocked
from app.profiles.repositories.contacts import BlockedUserRepository

OWNER_ID = 1
TARGET_ID = 9001


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestBlockUserCommand:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> BlockUserCommandHandler:
        return await request_container.get(BlockUserCommandHandler)

    async def test_user_is_blocked_and_event_published(
        self,
        handler: BlockUserCommandHandler,
        user_jwt: UserJWTData,
        blocked_repository: BlockedUserRepository,
        mock_event_bus,
    ) -> None:
        await handler.handle(
            BlockUserCommand(owner_id=OWNER_ID, target_id=TARGET_ID, user_jwt_data=user_jwt)
        )

        assert await blocked_repository.get(OWNER_ID, TARGET_ID) is not None
        assert mock_event_bus.one_of_type(UserBlocked).target_id == TARGET_ID

    async def test_block_list_cache_is_dropped(
        self,
        handler: BlockUserCommandHandler,
        user_jwt: UserJWTData,
        blocked_repository: BlockedUserRepository,
        redis_client,
    ) -> None:
        assert await blocked_repository.get_block_list(OWNER_ID) == set()
        assert await redis_client.get(ContactKeys.block_list(OWNER_ID)) is not None

        await handler.handle(
            BlockUserCommand(owner_id=OWNER_ID, target_id=TARGET_ID, user_jwt_data=user_jwt)
        )

        assert await redis_client.get(ContactKeys.block_list(OWNER_ID)) is None
        assert await blocked_repository.get_block_list(OWNER_ID) == {TARGET_ID}

    async def test_second_block_is_a_noop(
        self,
        handler: BlockUserCommandHandler,
        user_jwt: UserJWTData,
        mock_event_bus,
    ) -> None:
        command = BlockUserCommand(
            owner_id=OWNER_ID, target_id=TARGET_ID, user_jwt_data=user_jwt
        )

        await handler.handle(command)
        await handler.handle(command)

        assert len(mock_event_bus.of_type(UserBlocked)) == 1

    async def test_self_block_is_rejected(
        self, handler: BlockUserCommandHandler, user_jwt: UserJWTData
    ) -> None:
        with pytest.raises(SelfContactError):
            await handler.handle(
                BlockUserCommand(owner_id=OWNER_ID, target_id=OWNER_ID, user_jwt_data=user_jwt)
            )


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestUnblockUserCommand:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> UnblockUserCommandHandler:
        return await request_container.get(UnblockUserCommandHandler)

    async def test_block_is_removed_and_event_published(
        self,
        handler: UnblockUserCommandHandler,
        user_jwt: UserJWTData,
        make_block,
        blocked_repository: BlockedUserRepository,
        mock_event_bus,
    ) -> None:
        await make_block(OWNER_ID, TARGET_ID)

        await handler.handle(
            UnblockUserCommand(owner_id=OWNER_ID, target_id=TARGET_ID, user_jwt_data=user_jwt)
        )

        assert await blocked_repository.get(OWNER_ID, TARGET_ID) is None
        assert mock_event_bus.one_of_type(UserUnblocked).target_id == TARGET_ID

    async def test_unblocking_a_free_user_is_a_noop(
        self,
        handler: UnblockUserCommandHandler,
        user_jwt: UserJWTData,
        mock_event_bus,
    ) -> None:
        await handler.handle(
            UnblockUserCommand(owner_id=OWNER_ID, target_id=TARGET_ID, user_jwt_data=user_jwt)
        )

        assert mock_event_bus.published_events == []
