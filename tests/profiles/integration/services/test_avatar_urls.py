import pytest
from dishka import AsyncContainer
from httpx import AsyncClient
from redis.asyncio import Redis

from app.core.services.storage.aioboto.client import S3Client
from app.profiles.config import profile_config
from app.profiles.dtos.profiles import ProfileDTO
from app.profiles.keys import ProfileAvatarKeys
from app.profiles.services.avatar_urls import ProfileAvatarUrlService
from tests.support.http import assert_presigned_url

AVATAR_BYTES = b"avatar-bytes"


def profile_dto(user_id: int, avatars: dict) -> ProfileDTO:
    return ProfileDTO(
        id=user_id,
        username=f"user{user_id}",
        avatars=avatars,
        specialization=None,
        display_name=None,
        bio=None,
        date_birthday=None,
        skills=set(),
        links=[],
    )


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestProfileAvatarUrlService:

    @pytest.fixture
    async def service(self, di_container: AsyncContainer) -> ProfileAvatarUrlService:
        return await di_container.get(ProfileAvatarUrlService)

    @pytest.fixture
    async def stored_avatar(self, s3_test_client: S3Client) -> str:
        file_key = "7/64.jpg"
        await s3_test_client.put_object(
            Bucket=profile_config.AVATAR_BUCKET, Key=file_key, Body=AVATAR_BYTES
        )
        return file_key

    async def test_keys_are_replaced_with_signed_urls(
        self, service: ProfileAvatarUrlService, stored_avatar: str
    ) -> None:
        profile = profile_dto(7, {64: {"jpg": stored_avatar}})

        await service.attach([profile])

        url = profile.avatars[64]["jpg"]
        assert_presigned_url(url, bucket=profile_config.AVATAR_BUCKET, file_key=stored_avatar)

        async with AsyncClient() as client:
            response = await client.get(url)

        assert response.status_code == 200
        assert response.content == AVATAR_BYTES

    async def test_object_is_not_served_without_a_signature(
        self, stored_avatar: str, storage_endpoint: str
    ) -> None:
        async with AsyncClient(base_url=storage_endpoint) as client:
            response = await client.get(f"/{profile_config.AVATAR_BUCKET}/{stored_avatar}")

        assert response.status_code in (401, 403, 404)

    async def test_signature_is_taken_from_the_cache(
        self, service: ProfileAvatarUrlService, redis_client: Redis, stored_avatar: str
    ) -> None:
        await redis_client.set(ProfileAvatarKeys.download_url(stored_avatar), "https://cached/url")
        profile = profile_dto(7, {64: {"jpg": stored_avatar}})

        await service.attach([profile])

        assert profile.avatars[64]["jpg"] == "https://cached/url"

    async def test_fresh_signature_is_cached(
        self, service: ProfileAvatarUrlService, redis_client: Redis, stored_avatar: str
    ) -> None:
        profile = profile_dto(7, {64: {"jpg": stored_avatar}})

        await service.attach([profile])

        cached = await redis_client.get(ProfileAvatarKeys.download_url(stored_avatar))
        assert cached == profile.avatars[64]["jpg"]
        ttl = await redis_client.ttl(ProfileAvatarKeys.download_url(stored_avatar))
        assert 0 < ttl <= profile_config.AVATAR_URL_TTL - profile_config.AVATAR_URL_CACHE_SKEW

    async def test_every_variant_is_signed_once_per_key(
        self, service: ProfileAvatarUrlService, redis_client: Redis
    ) -> None:
        shared = "9/64.jpg"
        first = profile_dto(9, {64: {"jpg": shared, "webp": "9/64.webp"}})
        second = profile_dto(9, {64: {"jpg": shared}})

        await service.attach([first, second, None])

        assert first.avatars[64]["jpg"] == second.avatars[64]["jpg"]
        assert first.avatars[64]["webp"] != first.avatars[64]["jpg"]
        assert await redis_client.exists(ProfileAvatarKeys.download_url("9/64.webp"))

    async def test_profile_without_an_avatar_is_untouched(
        self, service: ProfileAvatarUrlService
    ) -> None:
        profile = profile_dto(7, {})

        await service.attach([profile])

        assert profile.avatars == {}
