import asyncio
import contextlib
import io
import logging
import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import magic
import pyvips  # type: ignore[import-untyped]

from app.core.services.storage.dtos import UploadFile
from app.core.services.storage.exceptions import StorageError
from app.core.services.storage.service import StorageService
from app.profiles.config import profile_config
from app.profiles.exceptions import AvatarNotImageTypeError, AvatarSizeError
from app.profiles.models.profile import AvatarMap, SizeAvatar, TypeImageAvatar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderedAvatar:
    size: SizeAvatar
    fmt: TypeImageAvatar
    content: bytes


@dataclass
class ProfilePhotoStorage:
    storage_service: StorageService

    async def load_validated(self, file_key: str) -> bytes:
        stat = await self.storage_service.get_stat(profile_config.PENDING_AVATAR_BUCKET, file_key)
        if stat.size > profile_config.AVATAR_MAX_SIZE:
            raise AvatarSizeError(current_size=stat.size)

        data = await self.storage_service.download_bytes(
            profile_config.PENDING_AVATAR_BUCKET,
            file_key,
            max_bytes=profile_config.AVATAR_MAX_SIZE,
            stat=stat,
        )

        mime = magic.from_buffer(data, mime=True)
        if mime not in profile_config.AVATAR_ALLOWED_MIMES:
            raise AvatarNotImageTypeError(type_avatar=mime)

        return data

    async def render(self, data: bytes) -> list[RenderedAvatar]:
        return await asyncio.to_thread(self._render, data)

    async def upload_variants(
        self, user_id: int, photo_id: UUID, rendered: list[RenderedAvatar]
    ) -> AvatarMap:
        keys = [f"{user_id}/{photo_id}/{item.size.value}.{item.fmt.value}" for item in rendered]
        await asyncio.gather(*(
            self.storage_service.upload_file(
                UploadFile(
                    bucket_name=profile_config.AVATAR_BUCKET,
                    file_key=key,
                    file_content=io.BytesIO(item.content),
                    size=len(item.content),
                    content_type=mimetypes.guess_type(key)[0],
                )
            )
            for key, item in zip(keys, rendered, strict=True)
        ))

        avatars: AvatarMap = {}
        for key, item in zip(keys, rendered, strict=True):
            avatars.setdefault(item.size.value, {})[item.fmt.value] = key
        return avatars

    async def delete_variants(
        self, user_id: int, avatars: Mapping[Any, Mapping[Any, str]] | None
    ) -> None:
        if not avatars:
            return

        keys = {
            key
            for variants in avatars.values()
            if isinstance(variants, Mapping)
            for key in variants.values()
            if isinstance(key, str)
        }
        for key in keys:
            if not key.startswith(f"{user_id}/"):
                continue

            try:
                await self.storage_service.delete_file(profile_config.AVATAR_BUCKET, key)
            except StorageError:
                logger.warning("Failed to delete profile photo variant", extra={"s3_key": key})

    async def drop_pending(self, file_key: str) -> None:
        with contextlib.suppress(StorageError):
            await self.storage_service.delete_file(profile_config.PENDING_AVATAR_BUCKET, file_key)

    @staticmethod
    def _render(data: bytes) -> list[RenderedAvatar]:
        img: pyvips.Image = pyvips.Image.new_from_buffer(data, "", access="random")  # type: ignore
        width, height = int(img.width), int(img.height)  # type: ignore
        if width <= 0 or height <= 0 or width * height > profile_config.AVATAR_MAX_PIXELS:
            raise AvatarSizeError(current_size=width * height)

        rendered: list[RenderedAvatar] = []
        for size in SizeAvatar:
            thumb = img.thumbnail_image(size, height=size, crop="centre")  # type: ignore
            for image_type in TypeImageAvatar:
                content: bytes = thumb.write_to_buffer(f".{image_type.value}", strip=True)  # type: ignore
                rendered.append(RenderedAvatar(size=size, fmt=image_type, content=content))

        return rendered
