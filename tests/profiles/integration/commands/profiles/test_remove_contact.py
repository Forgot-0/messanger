import pytest
from dishka import AsyncContainer

from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.exceptions import AccessDeniedError
from app.profiles.commands.profiles.remove_contact import (
    RemoveContactToProfileCommand,
    RemoveContactToProfileCommandHandler,
)
from app.profiles.exceptions import NotFoundProfileError
from app.profiles.models.profile import Profile
from app.profiles.repositories.profiles import ProfileRepository


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestRemoveContactFromProfileCommand:

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> RemoveContactToProfileCommandHandler:
        return await request_container.get(RemoveContactToProfileCommandHandler)

    async def test_owner_can_remove_contact_success(
        self,
        persisted_profile_contact,
        user_jwt: UserJWTData,
        handler: RemoveContactToProfileCommandHandler,
        profile_repository: ProfileRepository,
    ) -> None:
        profile = await persisted_profile_contact([("github", "https://github.com/testuser")])

        command = RemoveContactToProfileCommand(
            profile_id=profile.id,
            provider="github",
            user_jwt_data=user_jwt,
        )

        await handler.handle(command)

        updated = await profile_repository.get_by_id(profile.id)
        assert updated is not None
        assert all(
            contact.provider != "github"
            for contact in updated.contacts
        )

    async def test_remove_one_contact_keeps_others(
        self,
        persisted_profile_contact,
        user_jwt: UserJWTData,
        handler: RemoveContactToProfileCommandHandler,
        profile_repository: ProfileRepository,
    ) -> None:
        profile = await persisted_profile_contact([
            ("github", "https://github.com/testuser"),
            ("linkedin", "https://linkedin.com/in/testuser"),
            ("twitter", "https://twitter.com/testuser")
        ])

        command = RemoveContactToProfileCommand(
            profile_id=profile.id,
            provider="github",
            user_jwt_data=user_jwt,
        )

        await handler.handle(command)

        updated = await profile_repository.get_by_id(profile.id)
        assert updated is not None
        assert all(
            contact.provider != "github"
            for contact in updated.contacts
        )
        assert any(
            contact.provider == "linkedin"
            for contact in updated.contacts
        )
        assert any(
            contact.provider != "twitter"
            for contact in updated.contacts
        )

    async def test_not_found_raises(
        self,
        user_jwt: UserJWTData,
        handler: RemoveContactToProfileCommandHandler,
    ) -> None:
        command = RemoveContactToProfileCommand(
            profile_id=999999,
            provider="github",
            user_jwt_data=user_jwt,
        )

        with pytest.raises(NotFoundProfileError):
            await handler.handle(command)

    async def test_forbidden_if_not_owner_and_no_permission(
        self,
        persisted_profile_contact,
        make_user_jwt,
        handler: RemoveContactToProfileCommandHandler,
    ) -> None:
        profile = await persisted_profile_contact([
            ("github", "https://github.com/testuser")
        ])

        command = RemoveContactToProfileCommand(
            profile_id=profile.id,
            provider="github",
            user_jwt_data=make_user_jwt(id="3", username="other_user"),
        )

        with pytest.raises(AccessDeniedError):
            await handler.handle(command)

    async def test_allowed_if_not_owner_but_has_permission(
        self,
        persisted_profile_contact,
        super_admin_user_jwt: UserJWTData,
        handler: RemoveContactToProfileCommandHandler,
        profile_repository: ProfileRepository,
    ) -> None:
        profile = await persisted_profile_contact([
            ("twitter", "https://twitter.com/testuser")
        ])

        command = RemoveContactToProfileCommand(
            profile_id=profile.id,
            provider="twitter",
            user_jwt_data=super_admin_user_jwt,
        )

        await handler.handle(command)

        updated = await profile_repository.get_by_id(profile.id)
        assert updated is not None
        assert all(
            contact.provider != "twitter"
            for contact in updated.contacts
        )

    async def test_remove_non_existing_contact(
        self,
        persisted_profile: Profile,
        user_jwt: UserJWTData,
        handler: RemoveContactToProfileCommandHandler,
        profile_repository: ProfileRepository,
    ) -> None:
        command = RemoveContactToProfileCommand(
            profile_id=persisted_profile.id,
            provider="github",
            user_jwt_data=user_jwt,
        )

        await handler.handle(command)

        updated = await profile_repository.get_by_id(persisted_profile.id)
        assert updated is not None
        assert len(updated.contacts) == 0
