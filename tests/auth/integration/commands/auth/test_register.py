import pytest
from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.commands.users.register import RegisterCommand, RegisterCommandHandler
from app.auth.exceptions import DuplicateUserError, PasswordMismatchError
from app.auth.models.user import User
from app.auth.repositories.user import UserRepository
from app.auth.services.hash import HashService
from app.core.outbox.model import OutboxMessage
from tests.auth.integration.factories import AuthCommandFactory


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestRegisterCommand:
    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer
    ) -> RegisterCommandHandler:
        return await request_container.get(RegisterCommandHandler)

    async def test_register_new_user_success(
        self,
        user_repository: UserRepository,
        handler: RegisterCommandHandler,
    ) -> None:
        cmd_data = AuthCommandFactory.create_register_command(
            username="newuser",
            email="new@example.com",
        )

        command = RegisterCommand(**cmd_data)

        user_dto = await handler.handle(command)

        assert user_dto is not None
        assert user_dto.username == "newuser"
        assert user_dto.email == "new@example.com"
        assert user_dto.is_active is True
        assert user_dto.is_verified is False

        created_user = await user_repository.get_by_username(user_dto.username)
        assert created_user is not None
        assert created_user.password_hash is not None

    async def test_register_duplicate_username(
        self,
        handler: RegisterCommandHandler,
        standard_user: User,
    ) -> None:
        cmd_data = AuthCommandFactory.create_register_command(
            username=standard_user.username,
            email="different@example.com",
        )

        command = RegisterCommand(**cmd_data)

        with pytest.raises(DuplicateUserError) as exc_info:
            await handler.handle(command)

        assert exc_info.value.field == "username"
        assert exc_info.value.value == standard_user.username

    async def test_register_duplicate_email(
        self,
        handler: RegisterCommandHandler,
        standard_user: User,
    ) -> None:
        cmd_data = AuthCommandFactory.create_register_command(
            username="differentuser",
            email=standard_user.email,
        )

        command = RegisterCommand(**cmd_data)

        with pytest.raises(DuplicateUserError) as exc_info:
            await handler.handle(command)

        assert exc_info.value.field == "email"
        assert exc_info.value.value == standard_user.email

    async def test_register_password_mismatch(
        self,
        handler: RegisterCommandHandler,
    ) -> None:
        command = RegisterCommand(
            username="testuser",
            email="test@example.com",
            password="TestPass123!",
            password_repeat="DifferentPass123!",
        )

        with pytest.raises(PasswordMismatchError):
            await handler.handle(command)

    async def test_register_user_has_default_role(
        self,
        user_repository: UserRepository,
        handler: RegisterCommandHandler,
    ) -> None:
        cmd_data = AuthCommandFactory.create_register_command()
        command = RegisterCommand(**cmd_data)

        user_dto = await handler.handle(command)

        created_user = await user_repository.get_user_with_permission_by_id(user_dto.id)
        assert created_user is not None
        assert len(created_user.roles) == 1
        assert list(created_user.roles)[0].name == "user"

    async def test_register_writes_created_event_to_outbox(
        self,
        db_session: AsyncSession,
        handler: RegisterCommandHandler,
    ) -> None:
        cmd_data = AuthCommandFactory.create_register_command(
            username="outboxuser",
            email="outbox@example.com",
        )

        user_dto = await handler.handle(RegisterCommand(**cmd_data))

        result = await db_session.execute(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == user_dto.username)
        )
        outbox = result.scalars().all()

        assert len(outbox) == 1
        message = outbox[0]
        assert message.event_name == "auth.user.created"
        assert message.topic == "auth"
        assert message.aggregate_type == "user"
        assert message.payload["email"] == user_dto.email
        assert message.payload["username"] == user_dto.username

    async def test_register_password_is_hashed(
        self,
        user_repository: UserRepository,
        hash_service: HashService,
        handler: RegisterCommandHandler,
    ) -> None:
        plain_password = "TestPass123!"
        cmd_data = AuthCommandFactory.create_register_command(password=plain_password)
        command = RegisterCommand(**cmd_data)

        user_dto = await handler.handle(command)

        created_user = await user_repository.get_by_id(user_dto.id)
        assert created_user is not None
        assert created_user.password_hash is not None
        assert created_user.password_hash != plain_password
        assert hash_service.verify_password(plain_password, created_user.password_hash)
