import asyncio
import contextlib
import io
import logging
import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

import magic
import pyvips

from app.chats.config import chat_config
from app.chats.exceptions import ChatAvatarValidationError
from app.chats.repositories.avatar_upload import ChatAvatarUploadSlot
from app.core.services.storage.dtos import UploadFile
from app.core.services.storage.exceptions import StorageError
from app.core.services.storage.service import StorageService

logger = logging.getLogger(__name__)

MAGIC_HEADER_BYTES = 2048


@dataclass(frozen=True)
class RenderedAvatar:
    size: int
    fmt: str
    content: bytes


@dataclass
class ChatAvatarService:
    storage_service: StorageService

    async def load_validated(self, slot: ChatAvatarUploadSlot) -> bytes:
        stat = await self.storage_service.get_stat(
            chat_config.CHAT_AVATAR_BUCKET_PENDING, slot.s3_key
        )
        limit = min(slot.file_size, chat_config.CHAT_AVATAR_MAX_SIZE)
        if stat.size <= 0 or stat.size > limit:
            raise ChatAvatarValidationError(reason="size", file_size=stat.size)

        data = await self.storage_service.download_bytes(
            chat_config.CHAT_AVATAR_BUCKET_PENDING,
            slot.s3_key,
            max_bytes=chat_config.CHAT_AVATAR_MAX_SIZE,
            stat=stat,
        )

        mime_type = magic.from_buffer(data[:MAGIC_HEADER_BYTES], mime=True)
        if mime_type not in chat_config.CHAT_AVATAR_ALLOWED_MIMES:
            raise ChatAvatarValidationError(reason="mime_type", mime_type=mime_type)

        return data

    async def render(self, data: bytes) -> list[RenderedAvatar]:
        return await asyncio.to_thread(self._render, data)

    async def upload_variants(
        self, chat_id: UUID, version: UUID, rendered: list[RenderedAvatar]
    ) -> dict[str, dict[str, str]]:
        keys = [f"{chat_id}/{version}/{item.size}.{item.fmt}" for item in rendered]
        urls = await asyncio.gather(*(
            self.storage_service.upload_file(
                UploadFile(
                    bucket_name=chat_config.CHAT_AVATAR_BUCKET,
                    file_key=key,
                    file_content=io.BytesIO(item.content),
                    size=len(item.content),
                    content_type=mimetypes.guess_type(key)[0],
                )
            )
            for key, item in zip(keys, rendered, strict=True)
        ))

        avatars: dict[str, dict[str, str]] = {}
        for item, url in zip(rendered, urls, strict=True):
            avatars.setdefault(str(item.size), {})[item.fmt] = url
        return avatars

    async def delete_variants(self, avatars: Mapping[str, Mapping[str, str]] | None) -> None:
        if not avatars:
            return

        prefix = self.storage_service.get_public_url_object(chat_config.CHAT_AVATAR_BUCKET, "")
        keys = [
            url.removeprefix(prefix)
            for variants in avatars.values()
            for url in variants.values()
            if isinstance(url, str) and url.startswith(prefix)
        ]
        for key in keys:
            try:
                await self.storage_service.delete_file(chat_config.CHAT_AVATAR_BUCKET, key)
            except StorageError:
                logger.warning("Failed to delete stale chat avatar", extra={"s3_key": key})

    async def drop_pending(self, slot: ChatAvatarUploadSlot) -> None:
        with contextlib.suppress(StorageError):
            await self.storage_service.delete_file(
                chat_config.CHAT_AVATAR_BUCKET_PENDING, slot.s3_key
            )

    @staticmethod
    def _render(data: bytes) -> list[RenderedAvatar]:
        try:
            image = pyvips.Image.new_from_buffer(data, "", access="random")  # type: ignore
        except pyvips.Error as exc:
            raise ChatAvatarValidationError(reason="undecodable") from exc

        width, height = int(image.width), int(image.height)  # type: ignore
        if width <= 0 or height <= 0 or width * height > chat_config.CHAT_AVATAR_MAX_PIXELS:
            raise ChatAvatarValidationError(reason="dimensions")

        rendered: list[RenderedAvatar] = []
        for size in chat_config.CHAT_AVATAR_SIZES:
            thumb = image.thumbnail_image(size, height=size, crop="centre")  # type: ignore
            for fmt in chat_config.CHAT_AVATAR_FORMATS:
                content = thumb.write_to_buffer(f".{fmt}", strip=True)  # type: ignore
                rendered.append(RenderedAvatar(size=size, fmt=fmt, content=content))

        return rendered
