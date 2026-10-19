import pytest
from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.commands.users.change_username import ChangeUsernameCommand, ChangeUsernameCommandHandler
from app.auth.exceptions import InvalidUsernameError, UsernameTakenError
from app.auth.models.user import ChangedUsernameEvent, User
from app.auth.repositories.user import UserRepository
from app.core.outbox.model import OutboxMessage
from tests.auth.integration.factories import UserFactory
from tests.mocks import RecordingEventBus
from tests.support.jwt import jwt_from_user


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestChangeUsernameCommand:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> ChangeUsernameCommandHandler:
        return await request_container.get(ChangeUsernameCommandHandler)

    async def test_username_is_changed_and_announced_through_the_outbox(
        self,
        handler: ChangeUsernameCommandHandler,
        standard_user: User,
        user_repository: UserRepository,
        mock_event_bus: RecordingEventBus,
        db_session: AsyncSession,
    ) -> None:
        result = await handler.handle(
            ChangeUsernameCommand(username="@fresh_name", user_jwt_data=jwt_from_user(standard_user))
        )

        assert result.username == "fresh_name"
        assert (await user_repository.get_by_username("fresh_name")) is not None
        assert (await user_repository.get_by_username("standarduser")) is None

        event = mock_event_bus.one_of_type(ChangedUsernameEvent)
        assert (event.user_id, event.old_username, event.username) == (
            standard_user.id, "standarduser", "fresh_name"
        )

        row = (
            await db_session.execute(
                select(OutboxMessage).where(OutboxMessage.event_name == "auth.user.username_changed")
            )
        ).scalar_one()
        assert row.topic == "auth"
        assert row.aggregate_id == str(standard_user.id)

    async def test_name_held_by_another_user_in_any_case_is_taken(
        self,
        handler: ChangeUsernameCommandHandler,
        standard_user: User,
        admin_user: User,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        with pytest.raises(UsernameTakenError) as exc_info:
            await handler.handle(
                ChangeUsernameCommand(username="AdminUser", user_jwt_data=jwt_from_user(standard_user))
            )

        assert exc_info.value.detail == {"username": "AdminUser"}
        assert mock_event_bus.of_type(ChangedUsernameEvent) == []

    async def test_own_name_in_another_case_is_allowed(
        self,
        handler: ChangeUsernameCommandHandler,
        standard_user: User,
    ) -> None:
        result = await handler.handle(
            ChangeUsernameCommand(username="StandardUser", user_jwt_data=jwt_from_user(standard_user))
        )

        assert result.username == "StandardUser"

    async def test_same_name_is_a_no_op(
        self,
        handler: ChangeUsernameCommandHandler,
        standard_user: User,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        result = await handler.handle(
            ChangeUsernameCommand(username="standarduser", user_jwt_data=jwt_from_user(standard_user))
        )

        assert result.username == "standarduser"
        assert mock_event_bus.of_type(ChangedUsernameEvent) == []

    @pytest.mark.parametrize(
        "username, reason",
        [("abc", "length"), ("bad name", "format"), ("Moderator", "reserved")],
    )
    async def test_rules_are_checked_before_the_database(
        self,
        handler: ChangeUsernameCommandHandler,
        standard_user: User,
        username: str,
        reason: str,
    ) -> None:
        with pytest.raises(InvalidUsernameError) as exc_info:
            await handler.handle(
                ChangeUsernameCommand(username=username, user_jwt_data=jwt_from_user(standard_user))
            )

        assert exc_info.value.reason == reason


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestUsernameUniqueness:

    async def test_lookup_ignores_case(
        self, user_repository: UserRepository, standard_user: User
    ) -> None:
        assert await user_repository.is_username_taken("STANDARDUSER") is True
        assert await user_repository.is_username_taken("someone_else") is False

    async def test_lookup_skips_the_owner(
        self, user_repository: UserRepository, standard_user: User
    ) -> None:
        assert not await user_repository.is_username_taken(
            "StandardUser", exclude_user_id=standard_user.id
        )

    async def test_database_refuses_a_name_differing_only_in_case(
        self, db_session: AsyncSession, standard_user: User
    ) -> None:
        with pytest.raises(IntegrityError, match="uq_users_username_lower"):
            async with db_session.begin_nested():
                db_session.add(UserFactory.create(username="StandardUser"))

    async def test_race_lost_on_the_index_is_reported_as_taken(
        self,
        handler: ChangeUsernameCommandHandler,
        standard_user: User,
        admin_user: User,
        user_repository: UserRepository,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Проверку занятости обогнал другой запрос — решает уникальный индекс."""

        async def looks_free(username: str, exclude_user_id: int | None = None) -> bool:
            return False

        monkeypatch.setattr(user_repository, "is_username_taken", looks_free)

        with pytest.raises(UsernameTakenError) as exc_info:
            await handler.handle(
                ChangeUsernameCommand(username="AdminUser", user_jwt_data=jwt_from_user(standard_user))
            )

        assert exc_info.value.detail == {"username": "AdminUser"}

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> ChangeUsernameCommandHandler:
        return await request_container.get(ChangeUsernameCommandHandler)
