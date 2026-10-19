import pytest
from dishka import AsyncContainer

from app.core.services.auth.dto import UserJWTData
from app.core.services.storage.aioboto.client import S3Client
from app.core.services.storage.exceptions import ObjectNotFoundError
from app.core.services.storage.service import StorageService
from app.profiles.commands.profiles.proccess_avatar import ProccessAvatarCommand, ProccessAvatarCommandHandler
from app.profiles.config import profile_config
from app.profiles.exceptions import AvatarNotImageTypeError, ProfilePhotosLimitError
from app.profiles.models.profile import Profile, ProfileUpdated, SizeAvatar, TypeImageAvatar
from app.profiles.repositories.photos import ProfilePhotoRepository
from app.profiles.repositories.profiles import ProfileRepository
from tests.mocks import RecordingEventBus
from tests.support.media import make_jpeg

HEIC_BYTES = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 256


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestProccessAvatarCommand:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> ProccessAvatarCommandHandler:
        return await request_container.get(ProccessAvatarCommandHandler)

    async def _upload(self, s3_test_client: S3Client, key: str, data: bytes) -> None:
        await s3_test_client.put_object(Bucket=profile_config.PENDING_AVATAR_BUCKET, Key=key, Body=data)

    async def test_jpeg_becomes_the_avatar(
        self,
        handler: ProccessAvatarCommandHandler,
        persisted_profile: Profile,
        user_jwt: UserJWTData,
        s3_test_client: S3Client,
        profile_repository: ProfileRepository,
        storage_service: StorageService,
    ) -> None:
        key = f"{user_jwt.id}/avatar.jpg"
        await self._upload(s3_test_client, key, make_jpeg(600, 600))

        await handler.handle(ProccessAvatarCommand(user_id=int(user_jwt.id), file_key=key))

        profile = await profile_repository.get_by_id(persisted_profile.id)
        assert profile is not None and profile.avatars and profile.photo_id is not None

        # Бакет приватный: в БД лежат ключи объектов, а не абсолютные публичные URL.
        # У каждого фото свой каталог, поэтому новая загрузка не перетирает прежнюю.
        assert set(profile.avatars) == {int(size) for size in SizeAvatar}
        for size, variants in profile.avatars.items():
            assert set(variants) == {image_type.value for image_type in TypeImageAvatar}
            for image_type, value in variants.items():
                assert value == f"{user_jwt.id}/{profile.photo_id}/{size}.{image_type}"
                stat = await storage_service.get_stat(profile_config.AVATAR_BUCKET, value)
                assert stat.size > 0

    async def test_upload_lands_in_the_history_as_the_main_photo(
        self,
        handler: ProccessAvatarCommandHandler,
        persisted_profile: Profile,
        make_photo,
        user_jwt: UserJWTData,
        s3_test_client: S3Client,
        profile_repository: ProfileRepository,
        photo_repository: ProfilePhotoRepository,
        storage_service: StorageService,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        older = await make_photo(persisted_profile, age=10, main=True)
        key = f"{user_jwt.id}/avatar.jpg"
        await self._upload(s3_test_client, key, make_jpeg(400, 400))

        await handler.handle(ProccessAvatarCommand(user_id=int(user_jwt.id), file_key=key))

        profile = await profile_repository.get_by_id(persisted_profile.id)
        assert profile is not None and profile.photo_id != older.id
        latest = await photo_repository.get_latest(persisted_profile.id)
        assert latest is not None and latest.id == profile.photo_id
        assert await photo_repository.count(persisted_profile.id) == 2

        # Прежнее фото осталось в истории вместе со своими объектами
        await storage_service.get_stat(profile_config.AVATAR_BUCKET, older.avatars[64]["jpg"])

        event = mock_event_bus.one_of_type(ProfileUpdated)
        assert event.avatars == profile.avatars

        with pytest.raises(ObjectNotFoundError):
            await storage_service.get_stat(profile_config.PENDING_AVATAR_BUCKET, key)

    async def test_full_history_refuses_the_upload_and_cleans_up(
        self,
        handler: ProccessAvatarCommandHandler,
        persisted_profile: Profile,
        make_photo,
        user_jwt: UserJWTData,
        s3_test_client: S3Client,
        photo_repository: ProfilePhotoRepository,
        storage_service: StorageService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(profile_config, "MAX_PROFILE_PHOTOS", 1)
        await make_photo(persisted_profile, main=True)
        key = f"{user_jwt.id}/avatar.jpg"
        await self._upload(s3_test_client, key, make_jpeg(200, 200))
        before = await self._stored_keys(s3_test_client, f"{user_jwt.id}/")

        with pytest.raises(ProfilePhotosLimitError):
            await handler.handle(ProccessAvatarCommand(user_id=int(user_jwt.id), file_key=key))

        assert await photo_repository.count(persisted_profile.id) == 1
        # Отказ до рендера: в бакете ничего нового, pending-файл убран
        assert await self._stored_keys(s3_test_client, f"{user_jwt.id}/") == before
        with pytest.raises(ObjectNotFoundError):
            await storage_service.get_stat(profile_config.PENDING_AVATAR_BUCKET, key)

    async def _stored_keys(self, s3_test_client: S3Client, prefix: str) -> set[str]:
        listed = await s3_test_client.list_objects_v2(
            Bucket=profile_config.AVATAR_BUCKET, Prefix=prefix
        )
        return {item["Key"] for item in listed.get("Contents", [])}

    async def test_heic_is_refused_by_its_content(
        self,
        handler: ProccessAvatarCommandHandler,
        persisted_profile: Profile,
        user_jwt: UserJWTData,
        s3_test_client: S3Client,
        profile_repository: ProfileRepository,
    ) -> None:
        """Клиент перегоняет HEIC в JPEG сам: декодера HEVC в сборке pyvips нет."""
        key = f"{user_jwt.id}/avatar.jpg"
        await self._upload(s3_test_client, key, HEIC_BYTES)

        with pytest.raises(AvatarNotImageTypeError) as exc_info:
            await handler.handle(ProccessAvatarCommand(user_id=int(user_jwt.id), file_key=key))

        assert exc_info.value.type_avatar == "image/heic"
        profile = await profile_repository.get_by_id(persisted_profile.id)
        assert profile is not None and profile.avatars == {}
