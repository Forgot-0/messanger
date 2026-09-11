import pytest
from dishka import AsyncContainer

from app.profiles.commands.contacts.register_identifier import (
    RegisterUserIdentifierCommand,
    RegisterUserIdentifierCommandHandler,
)
from app.profiles.models.contacts import ContactAdded, ContactSource, IdentifierKind
from app.profiles.repositories.contacts import ContactIdentifierRepository, ContactRepository

NEW_USER_ID = 9100
WAITING_ONE = 9101
WAITING_TWO = 9102
EMAIL = "newcomer@example.com"


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestRegisterUserIdentifierCommand:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> RegisterUserIdentifierCommandHandler:
        return await request_container.get(RegisterUserIdentifierCommandHandler)

    async def test_identifier_is_stored_as_hmac(
        self,
        handler: RegisterUserIdentifierCommandHandler,
        identifier_repository: ContactIdentifierRepository,
        identifier_hasher,
    ) -> None:
        await handler.handle(
            RegisterUserIdentifierCommand(user_id=NEW_USER_ID, email=EMAIL)
        )

        identifier_hash = identifier_hasher.hash(IdentifierKind.EMAIL, EMAIL)
        assert await identifier_repository.resolve([identifier_hash]) == {
            identifier_hash: NEW_USER_ID
        }

    async def test_everyone_who_waited_gets_the_contact(
        self,
        handler: RegisterUserIdentifierCommandHandler,
        make_pending,
        contact_repository: ContactRepository,
    ) -> None:
        await make_pending(WAITING_ONE, EMAIL, first_name="Новичок")
        await make_pending(WAITING_TWO, EMAIL)

        resolved = await handler.handle(
            RegisterUserIdentifierCommand(user_id=NEW_USER_ID, email=EMAIL)
        )

        assert resolved == 2

        first = await contact_repository.get(WAITING_ONE, NEW_USER_ID)
        second = await contact_repository.get(WAITING_TWO, NEW_USER_ID)
        assert first is not None
        assert first.first_name == "Новичок"
        assert first.source is ContactSource.IMPORT
        assert second is not None

    async def test_pending_rows_are_consumed(
        self,
        handler: RegisterUserIdentifierCommandHandler,
        make_pending,
        identifier_repository: ContactIdentifierRepository,
    ) -> None:
        identifier_hash = await make_pending(WAITING_ONE, EMAIL)

        await handler.handle(RegisterUserIdentifierCommand(user_id=NEW_USER_ID, email=EMAIL))

        assert await identifier_repository.fetch_pending_batch(identifier_hash, limit=10) == []

    async def test_resolution_publishes_contact_added(
        self,
        handler: RegisterUserIdentifierCommandHandler,
        make_pending,
        mock_event_bus,
    ) -> None:
        await make_pending(WAITING_ONE, EMAIL)

        await handler.handle(RegisterUserIdentifierCommand(user_id=NEW_USER_ID, email=EMAIL))

        event = mock_event_bus.one_of_type(ContactAdded)
        assert event.owner_id == WAITING_ONE
        assert event.contact_id == NEW_USER_ID

    async def test_second_delivery_adds_nothing_new(
        self,
        handler: RegisterUserIdentifierCommandHandler,
        make_pending,
        mock_event_bus,
        contact_repository: ContactRepository,
    ) -> None:
        await make_pending(WAITING_ONE, EMAIL)
        command = RegisterUserIdentifierCommand(user_id=NEW_USER_ID, email=EMAIL)

        await handler.handle(command)
        await handler.handle(command)

        assert len(mock_event_bus.of_type(ContactAdded)) == 1
        assert await contact_repository.count(WAITING_ONE) == 1

    async def test_unparsable_email_is_skipped(
        self,
        handler: RegisterUserIdentifierCommandHandler,
        mock_event_bus,
    ) -> None:
        resolved = await handler.handle(
            RegisterUserIdentifierCommand(user_id=NEW_USER_ID, email="не почта")
        )

        assert resolved == 0
        assert mock_event_bus.published_events == []
