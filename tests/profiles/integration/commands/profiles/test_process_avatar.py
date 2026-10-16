import pytest
from dishka import AsyncContainer

from app.core.services.auth.dto import UserJWTData
from app.core.services.storage.aioboto.client import S3Client
from app.profiles.commands.profiles.proccess_avatar import ProccessAvatarCommand, ProccessAvatarCommandHandler
from app.profiles.config import profile_config
from app.profiles.exceptions import AvatarNotImageTypeError
from app.profiles.models.profile import Profile
from app.profiles.repositories.profiles import ProfileRepository
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
    ) -> None:
        key = f"{user_jwt.id}/avatar.jpg"
        await self._upload(s3_test_client, key, make_jpeg(600, 600))

        await handler.handle(ProccessAvatarCommand(user_id=int(user_jwt.id), file_key=key))

        profile = await profile_repository.get_by_id(persisted_profile.id)
        assert profile is not None and profile.avatars

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
