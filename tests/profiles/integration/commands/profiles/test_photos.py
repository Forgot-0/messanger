from uuid import uuid7

import pytest
from dishka import AsyncContainer

from app.core.services.auth.dto import UserJWTData
from app.core.services.storage.exceptions import ObjectNotFoundError
from app.core.services.storage.service import StorageService
from app.profiles.commands.profiles.delete_photo import (
    DeleteProfilePhotoCommand,
    DeleteProfilePhotoCommandHandler,
)
from app.profiles.commands.profiles.set_main_photo import (
    SetMainProfilePhotoCommand,
    SetMainProfilePhotoCommandHandler,
)
from app.profiles.config import profile_config
from app.profiles.exceptions import NotFoundProfilePhotoError
from app.profiles.models.photo import ProfilePhoto
from app.profiles.models.profile import Profile, ProfileUpdated
from app.profiles.repositories.photos import ProfilePhotoRepository
from app.profiles.repositories.profiles import ProfileRepository
from tests.mocks import RecordingEventBus


async def assert_deleted(storage_service: StorageService, photo: ProfilePhoto) -> None:
    for variants in photo.avatars.values():
        for key in variants.values():
            with pytest.raises(ObjectNotFoundError):
                await storage_service.get_stat(profile_config.AVATAR_BUCKET, key)


async def assert_stored(storage_service: StorageService, photo: ProfilePhoto) -> None:
    for variants in photo.avatars.values():
        for key in variants.values():
            await storage_service.get_stat(profile_config.AVATAR_BUCKET, key)


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestDeleteProfilePhoto:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> DeleteProfilePhotoCommandHandler:
        return await request_container.get(DeleteProfilePhotoCommandHandler)

    async def test_deleting_an_old_photo_keeps_the_main_one(
        self,
        handler: DeleteProfilePhotoCommandHandler,
        persisted_profile: Profile,
        make_photo,
        user_jwt: UserJWTData,
        profile_repository: ProfileRepository,
        photo_repository: ProfilePhotoRepository,
        storage_service: StorageService,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        old = await make_photo(persisted_profile, age=10)
        main = await make_photo(persisted_profile, main=True)

        await handler.handle(DeleteProfilePhotoCommand(user_jwt_data=user_jwt, photo_id=old.id))

        profile = await profile_repository.get_by_id(persisted_profile.id)
        assert profile is not None and profile.photo_id == main.id
        assert await photo_repository.count(persisted_profile.id) == 1
        assert mock_event_bus.of_type(ProfileUpdated) == []
        await assert_deleted(storage_service, old)
        await assert_stored(storage_service, main)

    async def test_deleting_the_main_photo_promotes_the_previous_one(
        self,
        handler: DeleteProfilePhotoCommandHandler,
        persisted_profile: Profile,
        make_photo,
        user_jwt: UserJWTData,
        profile_repository: ProfileRepository,
        storage_service: StorageService,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        oldest = await make_photo(persisted_profile, age=20)
        previous = await make_photo(persisted_profile, age=10)
        main = await make_photo(persisted_profile, main=True)

        await handler.handle(DeleteProfilePhotoCommand(user_jwt_data=user_jwt, photo_id=main.id))

        profile = await profile_repository.get_by_id(persisted_profile.id)
        assert profile is not None
        assert profile.photo_id == previous.id != oldest.id
        assert mock_event_bus.one_of_type(ProfileUpdated).avatars == previous.avatars
        await assert_deleted(storage_service, main)

    async def test_deleting_the_avatar_without_an_id_removes_the_main_photo(
        self,
        handler: DeleteProfilePhotoCommandHandler,
        persisted_profile: Profile,
        make_photo,
        user_jwt: UserJWTData,
        profile_repository: ProfileRepository,
        photo_repository: ProfilePhotoRepository,
        storage_service: StorageService,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        main = await make_photo(persisted_profile, main=True)

        await handler.handle(DeleteProfilePhotoCommand(user_jwt_data=user_jwt))

        profile = await profile_repository.get_by_id(persisted_profile.id)
        assert profile is not None
        assert profile.photo_id is None and profile.avatars == {}
        assert await photo_repository.count(persisted_profile.id) == 0
        assert mock_event_bus.one_of_type(ProfileUpdated).avatars == {}
        await assert_deleted(storage_service, main)

    async def test_deleting_the_avatar_when_there_is_none_is_a_no_op(
        self,
        handler: DeleteProfilePhotoCommandHandler,
        persisted_profile: Profile,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        await handler.handle(DeleteProfilePhotoCommand(user_jwt_data=user_jwt))

        assert mock_event_bus.of_type(ProfileUpdated) == []

    async def test_someone_elses_photo_is_not_found(
        self,
        handler: DeleteProfilePhotoCommandHandler,
        persisted_profile: Profile,
        make_profile,
        make_photo,
        make_user_jwt,
        storage_service: StorageService,
    ) -> None:
        stranger = await make_profile(5150, "stranger")
        photo = await make_photo(persisted_profile, main=True)

        with pytest.raises(NotFoundProfilePhotoError):
            await handler.handle(
                DeleteProfilePhotoCommand(
                    user_jwt_data=make_user_jwt(id=str(stranger.id)), photo_id=photo.id
                )
            )

        await assert_stored(storage_service, photo)

    async def test_unknown_photo_is_not_found(
        self,
        handler: DeleteProfilePhotoCommandHandler,
        persisted_profile: Profile,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotFoundProfilePhotoError):
            await handler.handle(DeleteProfilePhotoCommand(user_jwt_data=user_jwt, photo_id=uuid7()))


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestSetMainProfilePhoto:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> SetMainProfilePhotoCommandHandler:
        return await request_container.get(SetMainProfilePhotoCommandHandler)

    async def test_older_photo_becomes_main_and_first(
        self,
        handler: SetMainProfilePhotoCommandHandler,
        persisted_profile: Profile,
        make_photo,
        user_jwt: UserJWTData,
        profile_repository: ProfileRepository,
        photo_repository: ProfilePhotoRepository,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        old = await make_photo(persisted_profile, age=10)
        await make_photo(persisted_profile, main=True)

        await handler.handle(SetMainProfilePhotoCommand(photo_id=old.id, user_jwt_data=user_jwt))

        profile = await profile_repository.get_by_id(persisted_profile.id)
        assert profile is not None and profile.photo_id == old.id
        latest = await photo_repository.get_latest(persisted_profile.id)
        assert latest is not None and latest.id == old.id
        assert mock_event_bus.one_of_type(ProfileUpdated).avatars == old.avatars

    async def test_current_photo_is_a_no_op(
        self,
        handler: SetMainProfilePhotoCommandHandler,
        persisted_profile: Profile,
        make_photo,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        main = await make_photo(persisted_profile, main=True)

        await handler.handle(SetMainProfilePhotoCommand(photo_id=main.id, user_jwt_data=user_jwt))

        assert mock_event_bus.of_type(ProfileUpdated) == []

    async def test_someone_elses_photo_is_not_found(
        self,
        handler: SetMainProfilePhotoCommandHandler,
        persisted_profile: Profile,
        make_profile,
        make_photo,
        make_user_jwt,
    ) -> None:
        stranger = await make_profile(5151, "stranger")
        photo = await make_photo(persisted_profile)

        with pytest.raises(NotFoundProfilePhotoError):
            await handler.handle(
                SetMainProfilePhotoCommand(
                    photo_id=photo.id, user_jwt_data=make_user_jwt(id=str(stranger.id))
                )
            )
