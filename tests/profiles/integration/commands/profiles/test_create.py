import pytest
from dishka import AsyncContainer

from app.profiles.commands.profiles.create import CreateProfileCommand, CreateProfileCommandHanler
from app.profiles.exceptions import (
    AlreadeExistProfileError,
    TooLongBioError,
    TooLongDisplayNameError,
    TooLongSkillNameError,
)
from app.profiles.repositories.profiles import ProfileRepository
from tests.profiles.integration.factories import ProfileCommandFactory


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestCreateCommand:
    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
    ) -> CreateProfileCommandHanler:
        return await request_container.get(CreateProfileCommandHanler)

    async def test_create_success(
        self,
        profile_repository: ProfileRepository,
        handler: CreateProfileCommandHanler,
    ) -> None:
        cmd_data = ProfileCommandFactory.create_command(
            1, "test"
        )
        command = CreateProfileCommand(**cmd_data)
        await handler.handle(command)

        created_profile = await profile_repository.get_by_id(profile_id=1)

        assert created_profile is not None
        assert created_profile.username == "test"
        assert created_profile.bio is None
        assert created_profile.display_name is None
        assert isinstance(created_profile.skills, list)
        assert created_profile.skills == []

    async def test_create_duplicated(
        self,
        handler: CreateProfileCommandHanler,
    ) -> None:
        cmd_data = ProfileCommandFactory.create_command(
            1, "test"
        )
        command = CreateProfileCommand(**cmd_data)
        await handler.handle(command)

        with pytest.raises(AlreadeExistProfileError):
            await handler.handle(command)

    async def test_create_long_skill_name(
        self,
        handler: CreateProfileCommandHanler,
    ) -> None:
        cmd_data = ProfileCommandFactory.create_command(
            1, "test", skills={"1" * 1024}
        )
        command = CreateProfileCommand(**cmd_data)
        with pytest.raises(TooLongSkillNameError):
            await handler.handle(command)

    async def test_create_long_display_name(
        self,
        handler: CreateProfileCommandHanler,
    ) -> None:
        cmd_data = ProfileCommandFactory.create_command(
            1, "test", display_name="ab" * 1024
        )
        command = CreateProfileCommand(**cmd_data)
        with pytest.raises(TooLongDisplayNameError):
            await handler.handle(command)

    async def test_create_long_bio(
        self,
        handler: CreateProfileCommandHanler,
    ) -> None:
        cmd_data = ProfileCommandFactory.create_command(
            1, "test", bio="ab" * 1024
        )
        command = CreateProfileCommand(**cmd_data)
        with pytest.raises(TooLongBioError):
            await handler.handle(command)
