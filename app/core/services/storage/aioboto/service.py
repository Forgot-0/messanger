import asyncio
import logging
import mimetypes
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from app.core.services.storage.aioboto.client import S3Client
from app.core.services.storage.dtos import ObjectStat, UploadFile, UploadFilePost, UploadFilePostResponse
from app.core.services.storage.exceptions import (
    ObjectChangedError,
    ObjectNotFoundError,
    ObjectTooLargeError,
    StorageError,
)
from app.core.services.storage.policy import Policy
from app.core.services.storage.service import StorageService
from app.core.utils import now_utc

logger = logging.getLogger(__name__)

DOWNLOAD_CHUNK_SIZE = 256 * 1024

SSE_ALGORITHM = "AES256"

_NOT_FOUND_CODES = frozenset({"NoSuchKey", "NoSuchObject", "NoSuchVersion", "NoSuchBucket", "NotFound", "404"})
_PRECONDITION_CODES = frozenset({"PreconditionFailed", "412"})
_MISSING_POLICY_CODES = frozenset({"NoSuchBucketPolicy", "NotImplemented", "MethodNotAllowed"})
_BUCKET_EXISTS_CODES = frozenset({"BucketAlreadyExists", "BucketAlreadyOwnedByYou"})


@dataclass
class AioBotoStorageService(StorageService):
    client: S3Client
    public_client: S3Client
    bucket_policy: dict[str, Policy]
    public_base_url: str

    sse_enabled: bool = field(default=False)

    async def ensure_buckets(self) -> None:
        for bucket, policy in self.bucket_policy.items():
            try:
                await self._ensure_bucket(bucket)
            except ClientError:
                logger.exception("Failed to create bucket", extra={"bucket_name": bucket})
                continue

            await self._apply_policy(bucket, policy)

    async def _ensure_bucket(self, bucket: str) -> None:
        try:
            await self.client.head_bucket(Bucket=bucket)
            return
        except ClientError as exc:
            if self._code(exc) not in _NOT_FOUND_CODES:
                raise

        try:
            await self.client.create_bucket(Bucket=bucket)
        except ClientError as exc:
            if self._code(exc) not in _BUCKET_EXISTS_CODES:
                raise

        logger.info("Bucket created", extra={"bucket_name": bucket})

    async def _apply_policy(self, bucket: str, policy: Policy) -> None:
        try:
            if policy is Policy.NONE:
                await self.client.delete_bucket_policy(Bucket=bucket)
            else:
                await self.client.put_bucket_policy(Bucket=bucket, Policy=policy.bucket(bucket))
        except ClientError as exc:
            if self._code(exc) in _MISSING_POLICY_CODES:
                return
            logger.warning(
                "Failed to set bucket policy",
                extra={"bucket_name": bucket, "policy": policy.value, "error": str(exc)},
            )
            return

        logger.info("Policy set for bucket", extra={"bucket_name": bucket, "policy": policy.value})

    async def upload_put_url(self, bucket_name: str, file_key: str, expires: int) -> str:
        return await self.public_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket_name, "Key": file_key},
            ExpiresIn=expires,
        )

    async def upload_post_file(self, upload_file_post: UploadFilePost) -> UploadFilePostResponse:
        conditions: list[Any] = [
            ["content-length-range", upload_file_post.size_lower_limit, upload_file_post.size_upper_limit],
        ]

        if upload_file_post.content_type:
            operator = "eq" if upload_file_post.content_type.equals else "starts-with"
            conditions.append([operator, "$Content-Type", upload_file_post.content_type.text])
        else:
            conditions.append(["eq", "$Content-Type", self._guess_content_type(upload_file_post.file_key)])

        data = await self.public_client.generate_presigned_post(
            Bucket=upload_file_post.bucket_name,
            Key=f"{upload_file_post.file_key}${{filename}}",
            Conditions=conditions,
            ExpiresIn=upload_file_post.expires,
        )

        return UploadFilePostResponse(
            url=self.get_public_bucket_url(upload_file_post.bucket_name),
            fields=data["fields"],
        )

    async def upload_file(self, upload_file: UploadFile) -> str:
        if upload_file.bucket_name not in self.bucket_policy:
            raise ValueError("No exist bucket")

        content_type = upload_file.content_type or self._guess_content_type(upload_file.file_key)

        s3_metadata = {"uploaded_at": now_utc().isoformat()}
        if upload_file.metadata:
            s3_metadata.update({k: str(v) for k, v in upload_file.metadata.items()})

        is_private = self.bucket_policy[upload_file.bucket_name] is Policy.NONE

        params: dict[str, Any] = {
            "Bucket": upload_file.bucket_name,
            "Key": upload_file.file_key,
            "Body": upload_file.file_content,
            "ContentLength": upload_file.size,
            "ContentType": content_type,
            "Metadata": s3_metadata,
        }
        if self.sse_enabled and is_private:
            params["ServerSideEncryption"] = SSE_ALGORITHM

        try:
            await self.client.put_object(**params)
        except ClientError as exc:
            raise self._translate(exc, upload_file.bucket_name, upload_file.file_key) from exc

        logger.info(
            "File uploaded successfully",
            extra={"file_key": upload_file.file_key, "bucket_name": upload_file.bucket_name},
        )

        return (
            upload_file.file_key
            if is_private
            else self.get_public_url_object(upload_file.bucket_name, upload_file.file_key)
        )

    async def delete_file(self, bucket_name: str, file_key: str) -> bool:
        try:
            await self.client.delete_object(Bucket=bucket_name, Key=file_key)
        except ClientError as exc:
            raise self._translate(exc, bucket_name, file_key) from exc

        logger.info("File deleted successfully", extra={"file_key": file_key})
        return True

    async def generate_presigned_url(self, bucket_name: str, file_key: str, expires: int = 3600) -> str:
        return await self.public_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": file_key},
            ExpiresIn=expires,
        )

    async def download(self, bucket_name: str, file_key: str) -> bytes:
        try:
            response = await self.client.get_object(Bucket=bucket_name, Key=file_key)
            stream = response["Body"]
            async with stream:
                return await stream.read()
        except ClientError as exc:
            raise self._translate(exc, bucket_name, file_key) from exc

    async def download_range(self, bucket_name: str, file_key: str, offset: int, length: int) -> bytes:
        if length <= 0:
            return b""

        try:
            response = await self.client.get_object(
                Bucket=bucket_name,
                Key=file_key,
                Range=f"bytes={offset}-{offset + length - 1}",
            )
            stream = response["Body"]
            async with stream:
                return await stream.read()
        except ClientError as exc:
            raise self._translate(exc, bucket_name, file_key) from exc

    async def copy_object(
        self,
        bucket_from: str,
        file_key_from: str,
        bucket_to: str,
        file_key_to: str,
        source_stat: ObjectStat | None = None,
    ) -> None:
        copy_source: dict[str, str] = {"Bucket": bucket_from, "Key": file_key_from}
        params: dict[str, Any] = {"Bucket": bucket_to, "Key": file_key_to, "CopySource": copy_source}

        if source_stat is not None:
            if source_stat.version_id is not None:
                copy_source["VersionId"] = source_stat.version_id
            elif source_stat.etag:
                params["CopySourceIfMatch"] = self._quote_etag(source_stat.etag)

        try:
            await self.client.copy_object(**params)
        except ClientError as exc:
            raise self._translate(exc, bucket_from, file_key_from) from exc

    async def get_stat(self, bucket_name: str, file_key: str) -> ObjectStat:
        try:
            stat = await self.client.head_object(Bucket=bucket_name, Key=file_key)
        except ClientError as exc:
            raise self._translate(exc, bucket_name, file_key) from exc

        return ObjectStat(
            bucket_name=bucket_name,
            file_key=file_key,
            size=int(stat.get("ContentLength") or 0),
            etag=stat.get("ETag"),
            version_id=stat.get("VersionId"),
            content_type=stat.get("ContentType"),
        )

    async def download_to_path(
        self,
        bucket_name: str,
        file_key: str,
        destination: Path,
        *,
        max_bytes: int,
        stat: ObjectStat | None = None,
    ) -> int:
        file_obj = await asyncio.to_thread(destination.open, "wb")
        written = 0
        try:
            async for chunk in self._stream_pinned(bucket_name, file_key, max_bytes=max_bytes, stat=stat):
                written += len(chunk)
                await asyncio.to_thread(file_obj.write, chunk)
        finally:
            await asyncio.to_thread(file_obj.close)

        return written

    async def download_bytes(
        self,
        bucket_name: str,
        file_key: str,
        *,
        max_bytes: int,
        stat: ObjectStat | None = None,
    ) -> bytes:
        buffer = bytearray()
        async for chunk in self._stream_pinned(bucket_name, file_key, max_bytes=max_bytes, stat=stat):
            buffer.extend(chunk)

        return bytes(buffer)

    async def _stream_pinned(
        self,
        bucket_name: str,
        file_key: str,
        *,
        max_bytes: int,
        stat: ObjectStat | None,
    ) -> AsyncIterator[bytes]:
        params: dict[str, Any] = {"Bucket": bucket_name, "Key": file_key}

        if stat is not None:
            if stat.version_id is not None:
                params["VersionId"] = stat.version_id
            elif stat.etag:
                params["IfMatch"] = self._quote_etag(stat.etag)

        read = 0
        try:
            response = await self.client.get_object(**params)
            stream = response["Body"]
            async with stream:
                async for chunk in stream.iter_chunks(DOWNLOAD_CHUNK_SIZE):
                    read += len(chunk)
                    if read > max_bytes:
                        raise ObjectTooLargeError(
                            bucket_name=bucket_name,
                            file_key=file_key,
                            max_bytes=max_bytes,
                        )
                    yield chunk
        except ClientError as exc:
            raise self._translate(exc, bucket_name, file_key) from exc

    @staticmethod
    def _guess_content_type(file_key: str) -> str:
        content_type, _ = mimetypes.guess_type(file_key)
        return content_type or "application/octet-stream"

    @staticmethod
    def _quote_etag(etag: str) -> str:
        return etag if etag.startswith('"') else f'"{etag}"'

    @staticmethod
    def _code(exc: ClientError) -> str:
        error = exc.response.get("Error") or {}
        return str(error.get("Code") or "")

    @classmethod
    def _translate(cls, exc: ClientError, bucket_name: str, file_key: str) -> StorageError:
        code = cls._code(exc)
        if code in _NOT_FOUND_CODES:
            return ObjectNotFoundError(bucket_name=bucket_name, file_key=file_key)
        if code in _PRECONDITION_CODES:
            return ObjectChangedError(bucket_name=bucket_name, file_key=file_key)
        return StorageError()

    def get_public_url_object(self, bucket: str, file_key: str) -> str:
        return f"{self.public_base_url}/{bucket}/{file_key}"

    def get_public_bucket_url(self, bucket: str) -> str:
        return f"{self.public_base_url}/{bucket}"
