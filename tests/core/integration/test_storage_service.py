import io
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.services.storage.aioboto.client import S3Client
from app.core.services.storage.aioboto.service import AioBotoStorageService
from app.core.services.storage.dtos import ContentTypeFilter, UploadFile, UploadFilePost
from app.core.services.storage.exceptions import (
    ObjectChangedError,
    ObjectNotFoundError,
    ObjectTooLargeError,
)
from app.core.services.storage.policy import Policy
from app.profiles.config import profile_config

PRIVATE_BUCKET = "base"
PUBLIC_BUCKET = profile_config.AVATAR_BUCKET


def _key(suffix: str = ".bin") -> str:
    return f"core-storage/{uuid4()}{suffix}"


@pytest.mark.integration
@pytest.mark.core
@pytest.mark.asyncio
class TestAioBotoStorageService:

    @pytest.fixture
    def storage(self, storage_service: AioBotoStorageService) -> AioBotoStorageService:
        return storage_service

    async def _put(self, storage: AioBotoStorageService, key: str, data: bytes, bucket: str = PRIVATE_BUCKET) -> None:
        await storage.upload_file(
            UploadFile(
                bucket_name=bucket,
                file_content=io.BytesIO(data),
                file_key=key,
                size=len(data),
            )
        )

    async def test_upload_returns_key_for_private_bucket(self, storage: AioBotoStorageService) -> None:
        key = _key()
        result = await storage.upload_file(
            UploadFile(
                bucket_name=PRIVATE_BUCKET,
                file_content=io.BytesIO(b"payload"),
                file_key=key,
                size=7,
            )
        )

        assert result == key

    async def test_upload_returns_public_url_for_readable_bucket(self, storage: AioBotoStorageService) -> None:
        key = _key(".jpg")
        result = await storage.upload_file(
            UploadFile(
                bucket_name=PUBLIC_BUCKET,
                file_content=io.BytesIO(b"payload"),
                file_key=key,
                size=7,
            )
        )

        assert result == storage.get_public_url_object(PUBLIC_BUCKET, key)

    async def test_metadata_and_content_type_are_stored(self, storage: AioBotoStorageService) -> None:
        key = _key(".txt")
        await storage.upload_file(
            UploadFile(
                bucket_name=PRIVATE_BUCKET,
                file_content=io.BytesIO(b"payload"),
                file_key=key,
                size=7,
                metadata={"origin": "test"},
            )
        )

        stat = await storage.get_stat(PRIVATE_BUCKET, key)

        assert stat.size == 7
        assert stat.content_type == "text/plain"

    async def test_upload_rejects_unknown_bucket(self, storage: AioBotoStorageService) -> None:
        with pytest.raises(ValueError, match="No exist bucket"):
            await storage.upload_file(
                UploadFile(
                    bucket_name="not-declared",
                    file_content=io.BytesIO(b"x"),
                    file_key=_key(),
                    size=1,
                )
            )

    async def test_download_round_trip(self, storage: AioBotoStorageService) -> None:
        key, data = _key(), b"0123456789"
        await self._put(storage, key, data)

        assert await storage.download(PRIVATE_BUCKET, key) == data
        assert await storage.download_range(PRIVATE_BUCKET, key, 2, 3) == b"234"
        assert await storage.download_range(PRIVATE_BUCKET, key, 0, 0) == b""

    async def test_download_to_path_writes_every_byte(
        self, storage: AioBotoStorageService, tmp_path: Path
    ) -> None:
        key, data = _key(), b"chunked" * 5000
        await self._put(storage, key, data)
        destination = tmp_path / "out.bin"

        written = await storage.download_to_path(PRIVATE_BUCKET, key, destination, max_bytes=len(data))

        assert written == len(data)
        assert destination.read_bytes() == data

    async def test_download_stops_at_the_size_cap(self, storage: AioBotoStorageService) -> None:
        key, data = _key(), b"x" * 4096
        await self._put(storage, key, data)

        with pytest.raises(ObjectTooLargeError):
            await storage.download_bytes(PRIVATE_BUCKET, key, max_bytes=16)

    async def test_missing_object_is_reported_as_not_found(self, storage: AioBotoStorageService) -> None:
        missing = _key()

        with pytest.raises(ObjectNotFoundError):
            await storage.get_stat(PRIVATE_BUCKET, missing)
        with pytest.raises(ObjectNotFoundError):
            await storage.download(PRIVATE_BUCKET, missing)

    async def test_pinned_read_fails_when_the_object_changed(self, storage: AioBotoStorageService) -> None:
        key = _key()
        await self._put(storage, key, b"first")
        stale = await storage.get_stat(PRIVATE_BUCKET, key)
        await self._put(storage, key, b"second-and-different")

        with pytest.raises(ObjectChangedError):
            await storage.download_bytes(PRIVATE_BUCKET, key, max_bytes=1024, stat=stale)

    async def test_copy_honours_the_source_etag(self, storage: AioBotoStorageService) -> None:
        key, data = _key(), b"copy-me"
        await self._put(storage, key, data)
        stat = await storage.get_stat(PRIVATE_BUCKET, key)
        target = _key()

        await storage.copy_object(PRIVATE_BUCKET, key, PUBLIC_BUCKET, target, source_stat=stat)

        assert await storage.download(PUBLIC_BUCKET, target) == data

        stale = replace(stat, etag='"{}"'.format("0" * 32))
        with pytest.raises(ObjectChangedError):
            await storage.copy_object(PRIVATE_BUCKET, key, PUBLIC_BUCKET, _key(), source_stat=stale)

    async def test_delete_removes_the_object(self, storage: AioBotoStorageService) -> None:
        key = _key()
        await self._put(storage, key, b"temporary")

        assert await storage.delete_file(PRIVATE_BUCKET, key) is True
        with pytest.raises(ObjectNotFoundError):
            await storage.get_stat(PRIVATE_BUCKET, key)

    async def test_presigned_get_serves_a_private_object(self, storage: AioBotoStorageService) -> None:
        key, data = _key(), b"signed-get"
        await self._put(storage, key, data)

        url = await storage.generate_presigned_url(PRIVATE_BUCKET, key, expires=60)

        async with AsyncClient() as client:
            response = await client.get(url)

        assert response.status_code == 200
        assert response.content == data

    async def test_presigned_put_accepts_an_upload(self, storage: AioBotoStorageService) -> None:
        key, data = _key(), b"signed-put"

        url = await storage.upload_put_url(PRIVATE_BUCKET, key, expires=60)

        async with AsyncClient() as client:
            response = await client.put(url, content=data)

        assert response.status_code == 200
        assert await storage.download(PRIVATE_BUCKET, key) == data

    async def test_presigned_post_accepts_a_form_upload(self, storage: AioBotoStorageService) -> None:
        prefix = f"core-storage/{uuid4()}/"

        post = await storage.upload_post_file(
            UploadFilePost(
                bucket_name=PRIVATE_BUCKET,
                file_key=prefix,
                expires=60,
                size_upper_limit=1024,
                content_type=ContentTypeFilter(text="text/plain"),
            )
        )

        fields = {
            name: (f"{prefix}form.txt" if name == "key" else value)
            for name, value in post.fields.items()
        }
        fields["Content-Type"] = "text/plain"

        async with AsyncClient() as client:
            response = await client.post(
                post.url,
                data=fields,
                files={"file": ("form.txt", b"form-body", "text/plain")},
            )

        assert response.status_code == 204
        assert await storage.download(PRIVATE_BUCKET, f"{prefix}form.txt") == b"form-body"

    async def test_bucket_policy_decides_anonymous_access(
        self, storage: AioBotoStorageService, storage_endpoint: str
    ) -> None:
        private_key, public_key = _key(), _key(".jpg")
        await self._put(storage, private_key, b"secret")
        await self._put(storage, public_key, b"public", bucket=PUBLIC_BUCKET)

        async with AsyncClient(base_url=storage_endpoint) as client:
            public_response = await client.get(f"/{PUBLIC_BUCKET}/{public_key}")
            private_response = await client.get(f"/{PRIVATE_BUCKET}/{private_key}")

        assert public_response.status_code == 200
        assert private_response.status_code == 403

    async def test_ensure_buckets_is_idempotent(
        self, s3_test_client: S3Client, storage_endpoint: str
    ) -> None:
        service = AioBotoStorageService(
            client=s3_test_client,
            public_client=s3_test_client,
            bucket_policy={PRIVATE_BUCKET: Policy.NONE, PUBLIC_BUCKET: Policy.GET},
            public_base_url=storage_endpoint,
        )

        await service.ensure_buckets()
        await service.ensure_buckets()
