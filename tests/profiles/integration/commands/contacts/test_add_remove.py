import pytest
from dishka import AsyncContainer

from app.core.services.auth.dto import UserJWTData
from app.profiles.commands.contacts.add import AddContactCommand, AddContactCommandHandler
from app.profiles.commands.contacts.remove import RemoveContactCommand, RemoveContactCommandHandler
from app.profiles.commands.contacts.update import UpdateContactCommand, UpdateContactCommandHandler
from app.profiles.exceptions import (
    ContactBlockedError,
    NotFoundContactError,
    NotFoundContactTargetError,
    SelfContactError,
)
from app.profiles.models.contacts import ContactAdded, ContactRemoved, ContactSource
from app.profiles.repositories.contacts import ContactRepository

OWNER_ID = 1
FRIEND_ID = 8801


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestAddContactCommand:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> AddContactCommandHandler:
        return await request_container.get(AddContactCommandHandler)

    async def test_contact_is_added_by_user_id(
        self,
        handler: AddContactCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
        contact_repository: ContactRepository,
    ) -> None:
        await make_profile(FRIEND_ID, "friend", "Friend")

        dto = await handler.handle(
            AddContactCommand(
                owner_id=OWNER_ID,
                user_id=FRIEND_ID,
                first_name="Вася",
                user_jwt_data=user_jwt,
            )
        )

        assert dto.contact_id == FRIEND_ID
        assert dto.first_name == "Вася"
        assert dto.source is ContactSource.MANUAL
        assert dto.profile is not None
        assert dto.profile.display_name == "Friend"

        stored = await contact_repository.get(OWNER_ID, FRIEND_ID)
        assert stored is not None

    async def test_contact_is_added_by_username_case_insensitively(
        self,
        handler: AddContactCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
    ) -> None:
        await make_profile(FRIEND_ID, "Friend")

        dto = await handler.handle(
            AddContactCommand(owner_id=OWNER_ID, username="friend", user_jwt_data=user_jwt)
        )

        assert dto.contact_id == FRIEND_ID
        assert dto.source is ContactSource.USERNAME

    async def test_adding_publishes_contact_added(
        self,
        handler: AddContactCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
        mock_event_bus,
    ) -> None:
        await make_profile(FRIEND_ID, "friend")

        await handler.handle(
            AddContactCommand(owner_id=OWNER_ID, user_id=FRIEND_ID, user_jwt_data=user_jwt)
        )

        event = mock_event_bus.one_of_type(ContactAdded)
        assert event.owner_id == OWNER_ID
        assert event.contact_id == FRIEND_ID
        assert event.is_mutual is False

    async def test_mutual_flag_is_set_on_both_rows(
        self,
        handler: AddContactCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
        make_contact,
        contact_repository: ContactRepository,
        mock_event_bus,
    ) -> None:
        await make_profile(FRIEND_ID, "friend")
        await make_contact(FRIEND_ID, OWNER_ID)

        dto = await handler.handle(
            AddContactCommand(owner_id=OWNER_ID, user_id=FRIEND_ID, user_jwt_data=user_jwt)
        )

        assert dto.is_mutual is True
        assert mock_event_bus.one_of_type(ContactAdded).is_mutual is True

        reverse = await contact_repository.get(FRIEND_ID, OWNER_ID)
        assert reverse is not None
        assert reverse.is_mutual is True

    async def test_adding_twice_does_not_duplicate_the_row(
        self,
        handler: AddContactCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
        contact_repository: ContactRepository,
    ) -> None:
        await make_profile(FRIEND_ID, "friend")
        command = AddContactCommand(
            owner_id=OWNER_ID, user_id=FRIEND_ID, first_name="Вася", user_jwt_data=user_jwt
        )

        await handler.handle(command)
        await handler.handle(command)

        assert await contact_repository.count(OWNER_ID) == 1

    async def test_self_add_is_rejected(
        self, handler: AddContactCommandHandler, user_jwt: UserJWTData, make_profile
    ) -> None:
        await make_profile(OWNER_ID, "me")

        with pytest.raises(SelfContactError):
            await handler.handle(
                AddContactCommand(owner_id=OWNER_ID, user_id=OWNER_ID, user_jwt_data=user_jwt)
            )

    async def test_unknown_target_is_rejected(
        self, handler: AddContactCommandHandler, user_jwt: UserJWTData
    ) -> None:
        with pytest.raises(NotFoundContactTargetError):
            await handler.handle(
                AddContactCommand(owner_id=OWNER_ID, user_id=999999, user_jwt_data=user_jwt)
            )

    async def test_blocked_user_cannot_be_added(
        self,
        handler: AddContactCommandHandler,
        user_jwt: UserJWTData,
        make_profile,
        make_block,
    ) -> None:
        await make_profile(FRIEND_ID, "friend")
        await make_block(OWNER_ID, FRIEND_ID)

        with pytest.raises(ContactBlockedError):
            await handler.handle(
                AddContactCommand(owner_id=OWNER_ID, user_id=FRIEND_ID, user_jwt_data=user_jwt)
            )


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestRemoveContactCommand:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> RemoveContactCommandHandler:
        return await request_container.get(RemoveContactCommandHandler)

    async def test_contact_is_removed_and_event_published(
        self,
        handler: RemoveContactCommandHandler,
        user_jwt: UserJWTData,
        make_contact,
        contact_repository: ContactRepository,
        mock_event_bus,
    ) -> None:
        await make_contact(OWNER_ID, FRIEND_ID)

        await handler.handle(
            RemoveContactCommand(
                owner_id=OWNER_ID, contact_id=FRIEND_ID, user_jwt_data=user_jwt
            )
        )

        assert await contact_repository.get(OWNER_ID, FRIEND_ID) is None
        assert mock_event_bus.one_of_type(ContactRemoved).contact_id == FRIEND_ID

    async def test_removal_drops_mutual_flag_on_the_other_side(
        self,
        handler: RemoveContactCommandHandler,
        user_jwt: UserJWTData,
        make_contact,
        contact_repository: ContactRepository,
    ) -> None:
        await make_contact(OWNER_ID, FRIEND_ID, is_mutual=True)
        await make_contact(FRIEND_ID, OWNER_ID, is_mutual=True)

        await handler.handle(
            RemoveContactCommand(
                owner_id=OWNER_ID, contact_id=FRIEND_ID, user_jwt_data=user_jwt
            )
        )

        reverse = await contact_repository.get(FRIEND_ID, OWNER_ID)
        assert reverse is not None
        assert reverse.is_mutual is False

    async def test_missing_contact_is_an_error(
        self, handler: RemoveContactCommandHandler, user_jwt: UserJWTData
    ) -> None:
        with pytest.raises(NotFoundContactError):
            await handler.handle(
                RemoveContactCommand(
                    owner_id=OWNER_ID, contact_id=FRIEND_ID, user_jwt_data=user_jwt
                )
            )


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestUpdateContactCommand:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> UpdateContactCommandHandler:
        return await request_container.get(UpdateContactCommandHandler)

    async def test_local_name_and_favorite_are_updated(
        self,
        handler: UpdateContactCommandHandler,
        user_jwt: UserJWTData,
        make_contact,
    ) -> None:
        await make_contact(OWNER_ID, FRIEND_ID, first_name="Старое")

        dto = await handler.handle(
            UpdateContactCommand(
                owner_id=OWNER_ID,
                contact_id=FRIEND_ID,
                first_name="Новое",
                last_name="Имя",
                is_favorite=True,
                user_jwt_data=user_jwt,
            )
        )

        assert dto.first_name == "Новое"
        assert dto.last_name == "Имя"
        assert dto.is_favorite is True

    async def test_rename_does_not_publish_events(
        self,
        handler: UpdateContactCommandHandler,
        user_jwt: UserJWTData,
        make_contact,
        mock_event_bus,
    ) -> None:
        await make_contact(OWNER_ID, FRIEND_ID)

        await handler.handle(
            UpdateContactCommand(
                owner_id=OWNER_ID,
                contact_id=FRIEND_ID,
                first_name="Локальное",
                user_jwt_data=user_jwt,
            )
        )

        assert mock_event_bus.published_events == []

    async def test_missing_contact_is_an_error(
        self, handler: UpdateContactCommandHandler, user_jwt: UserJWTData
    ) -> None:
        with pytest.raises(NotFoundContactError):
            await handler.handle(
                UpdateContactCommand(
                    owner_id=OWNER_ID, contact_id=FRIEND_ID, user_jwt_data=user_jwt
                )
            )
