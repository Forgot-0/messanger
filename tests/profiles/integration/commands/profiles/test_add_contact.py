import pytest
from dishka import AsyncContainer

from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.exceptions import AccessDeniedError
from app.profiles.commands.profiles.add_contact import AddContactToProfileCommand, AddContactToProfileCommandHandler
from app.profiles.exceptions import NotFoundProfileError
from app.profiles.models.profile import Profile
from app.profiles.repositories.profiles import ProfileRepository


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestAddContactToProfileCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> AddContactToProfileCommandHandler:
        return await request_container.get(AddContactToProfileCommandHandler)

    async def test_owner_can_add_contact_success(
        self,
        persisted_profile: Profile,
        user_jwt: UserJWTData,
        handler,
        profile_repository: ProfileRepository,
    ) -> None:
        command = AddContactToProfileCommand(
            profile_id=persisted_profile.id,
            provider="github",
            contact="https://github.com/testuser",
            user_jwt_data=user_jwt,
        )

        await handler.handle(command)

        updated = await profile_repository.get_by_id(persisted_profile.id)
        assert updated is not None
        assert any(
            contact.contact == "https://github.com/testuser" and contact.provider == "github"
            for contact in updated.contacts
        )

    async def test_add_multiple_contacts(
        self,
        persisted_profile: Profile,
        user_jwt: UserJWTData,
        handler,
        profile_repository: ProfileRepository,
    ) -> None:
        command1 = AddContactToProfileCommand(
            profile_id=persisted_profile.id,
            provider="github",
            contact="https://github.com/testuser",
            user_jwt_data=user_jwt,
        )
        await handler.handle(command1)

        command2 = AddContactToProfileCommand(
            profile_id=persisted_profile.id,
            provider="linkedin",
            contact="https://linkedin.com/in/testuser",
            user_jwt_data=user_jwt,
        )
        await handler.handle(command2)

        updated = await profile_repository.get_by_id(persisted_profile.id)
        assert updated is not None
        assert any(
            contact.contact == "https://github.com/testuser" and contact.provider == "github"
            for contact in updated.contacts
        )
        assert any(
            contact.contact == "https://linkedin.com/in/testuser" and contact.provider == "linkedin"
            for contact in updated.contacts
        )

    async def test_not_found_raises(
        self,
        user_jwt: UserJWTData,
        handler,
    ) -> None:
        command = AddContactToProfileCommand(
            profile_id=999999,
            provider="github",
            contact="https://github.com/testuser",
            user_jwt_data=user_jwt,
        )

        with pytest.raises(NotFoundProfileError):
            await handler.handle(command)

    async def test_forbidden_if_not_owner_and_no_permission(
        self,
        persisted_profile: Profile,
        make_user_jwt,
        handler,
    ) -> None:
        command = AddContactToProfileCommand(
            profile_id=persisted_profile.id,
            provider="github",
            contact="https://github.com/testuser",
            user_jwt_data=make_user_jwt(id="3", username="other_user"),
        )

        with pytest.raises(AccessDeniedError):
            await handler.handle(command)

    async def test_allowed_if_not_owner_but_has_permission(
        self,
        persisted_profile: Profile,
        super_admin_user_jwt: UserJWTData,
        handler,
        profile_repository: ProfileRepository,
    ) -> None:
        command = AddContactToProfileCommand(
            profile_id=persisted_profile.id,
            provider="twitter",
            contact="https://twitter.com/testuser",
            user_jwt_data=super_admin_user_jwt,
        )

        await handler.handle(command)

        updated = await profile_repository.get_by_id(persisted_profile.id)
        assert updated is not None

        assert any(
            contact.contact == "https://twitter.com/testuser" and contact.provider == "twitter"
            for contact in updated.contacts
        )

    async def test_update_existing_contact(
        self,
        persisted_profile: Profile,
        user_jwt: UserJWTData,
        handler,
        profile_repository: ProfileRepository,
    ) -> None:

        command1 = AddContactToProfileCommand(
            profile_id=persisted_profile.id,
            provider="github",
            contact="https://github.com/olduser",
            user_jwt_data=user_jwt,
        )
        await handler.handle(command1)

        command2 = AddContactToProfileCommand(
            profile_id=persisted_profile.id,
            provider="github",
            contact="https://github.com/newuser",
            user_jwt_data=user_jwt,
        )
        await handler.handle(command2)

        updated = await profile_repository.get_by_id(persisted_profile.id)
        assert updated is not None
        assert any(
            contact.contact == "https://github.com/newuser" and contact.provider == "github"
            for contact in updated.contacts
        )
