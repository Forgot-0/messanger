from datetime import date

import pytest
from dishka import AsyncContainer

from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.exceptions import AccessDeniedError
from app.profiles.commands.profiles.update import UpdateProfileCommand, UpdateProfileCommandHandler
from app.profiles.exceptions import NotFoundProfileError
from app.profiles.models.profile import Profile
from app.profiles.repositories.profiles import ProfileRepository
from tests.profiles.integration.factories import ProfileCommandFactory


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestUpdateProfileHandler:
    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> UpdateProfileCommandHandler:
        return await request_container.get(UpdateProfileCommandHandler)

    @pytest.mark.parametrize(
        "payload, expected",
        [
            (
                ProfileCommandFactory.update_command(
                    display_name="new_name", bio="new bio", skills={"A", "b"}
                ),
                {"display_name": "new_name", "bio": "new bio", "skills": ["b", "a"]},
            ),
            (
                ProfileCommandFactory.update_command(display_name="only_name"),
                {"display_name": "only_name", "bio": None, "skills": []},
            ),
            (
                ProfileCommandFactory.update_command(skills=set()),
                {"display_name": None, "bio": None, "skills": []},
            ),
        ],
    )
    async def test_owner_can_update_profile(
        self,
        persisted_profile: Profile,
        user_jwt: UserJWTData,
        handler: UpdateProfileCommandHandler,
        profile_repository: ProfileRepository,
        payload,
        expected,
    ) -> None:
        command = UpdateProfileCommand(
            profile_id=persisted_profile.id,
            user_jwt_data=user_jwt,
            **payload,
        )

        await handler.handle(command)

        updated = await profile_repository.get_by_id(persisted_profile.id)
        assert updated is not None
        assert updated.display_name == expected["display_name"]
        assert updated.bio == expected["bio"]
        assert set(updated.skills) == set(expected["skills"])

    async def test_not_found_raises(
        self,
        handler: UpdateProfileCommandHandler,
        user_jwt: UserJWTData,
    ) -> None:
        command = UpdateProfileCommand(
            profile_id=999999,
            user_jwt_data=user_jwt,
            specialization="",
            display_name="x",
            bio=None,
            skills=None,
            date_birthday=None,
        )

        with pytest.raises(NotFoundProfileError):
            await handler.handle(command)

    async def test_forbidden_if_not_owner_and_no_permission(
        self,
        persisted_profile: Profile,
        make_user_jwt,
        handler: UpdateProfileCommandHandler,
    ) -> None:
        command = UpdateProfileCommand(
            profile_id=persisted_profile.id,
            user_jwt_data=make_user_jwt(id="3", username="other_user"),
            **ProfileCommandFactory.update_command(display_name="bad"),
        )

        with pytest.raises(AccessDeniedError):
            await handler.handle(command)

    async def test_allowed_if_not_owner_but_has_permission(
        self,
        persisted_profile: Profile,
        super_admin_user_jwt: UserJWTData,
        handler: UpdateProfileCommandHandler,
        profile_repository: ProfileRepository,
    ) -> None:
        command = UpdateProfileCommand(
            profile_id=persisted_profile.id,
            user_jwt_data=super_admin_user_jwt,
            **ProfileCommandFactory.update_command(
                display_name="admin_updated", bio="ok", skills={"x"}, date_birthday=date(2005, 2, 25)
            ),
        )

        await handler.handle(command)

        updated = await profile_repository.get_by_id(persisted_profile.id)
        assert updated
        assert updated.display_name == "admin_updated"
        assert updated.bio == "ok"
        assert updated.skills == ["x"]
        assert updated.date_birthday == date(2005, 2, 25)
