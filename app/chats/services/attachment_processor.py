import asyncio
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.chats.config import chat_config
from app.chats.exceptions import AttachmentMediaValidationError
from app.chats.keys import AttachmentStorageKeys
from app.chats.metrics import ATTACHMENT_MEDIA_DEGRADED
from app.chats.models.attachment import AttachmentType, MessageAttachment
from app.chats.services.attachment_images import AttachmentImageRenderer, RenderedMedia
from app.chats.services.attachment_media import AttachmentMediaValidator
from app.core.services.media.dtos import MediaInfo
from app.core.services.media.exceptions import MediaTranscodeError
from app.core.services.media.service import MediaTranscoder
from app.core.services.storage.dtos import ObjectStat, UploadFile
from app.core.services.storage.service import StorageService

logger = logging.getLogger(__name__)

VIDEO_CONTAINERS: dict[str, str] = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/x-msvideo": "avi",
}


@dataclass
class AttachmentMediaProcessor:
    storage_service: StorageService
    media_validator: AttachmentMediaValidator
    image_renderer: AttachmentImageRenderer
    media_transcoder: MediaTranscoder

    async def promote(self, attachment: MessageAttachment, stat: ObjectStat) -> None:
        match attachment.attachment_type:
            case AttachmentType.FILE:
                await self._copy_original(attachment, stat)
            case AttachmentType.VOICE:
                await self.media_validator.validate_and_apply(attachment, stat)
                await self._copy_original(attachment, stat)
            case AttachmentType.IMAGE:
                with TemporaryDirectory(prefix=f"attachment-{attachment.id}-") as tmp_dir:
                    workdir = Path(tmp_dir)
                    source = workdir / "source"
                    await self.media_validator.download(attachment, stat, source, chat_config.MAX_MEDIA_SIZE)
                    await self._promote_image(attachment, stat, source, workdir)
            case AttachmentType.VIDEO | AttachmentType.VIDEO_NOTE:
                max_bytes = self.media_validator.check_size(attachment, stat)
                with TemporaryDirectory(prefix=f"attachment-{attachment.id}-") as tmp_dir:
                    workdir = Path(tmp_dir)
                    source = workdir / "source"
                    await self.media_validator.download(attachment, stat, source, max_bytes)
                    media_info = await self.media_validator.inspect(attachment, source)
                    await self._promote_video(attachment, stat, source, workdir, media_info)

    async def _promote_image(
        self, attachment: MessageAttachment, stat: ObjectStat, source: Path, workdir: Path
    ) -> None:
        rendered = await self.image_renderer.render_photo(attachment, source, workdir)
        previews = await self._upload_previews(attachment, rendered.media)

        if rendered.original is None:
            await self._copy_original(attachment, stat)
        else:
            await self._upload_original(attachment, rendered.original)

        attachment.apply_media(
            width=rendered.width,
            height=rendered.height,
            previews=previews,
            thumbhash=rendered.media.thumbhash,
        )

    async def _promote_video(
        self,
        attachment: MessageAttachment,
        stat: ObjectStat,
        source: Path,
        workdir: Path,
        media_info: MediaInfo,
    ) -> None:
        stream = media_info.video_streams[0]
        original = await self._strip_video_metadata(attachment, source, workdir)

        previews: list[dict[str, Any]] = []
        thumbhash: str | None = None
        poster = workdir / "poster.png"
        try:
            await self.media_transcoder.extract_frame(
                original,
                poster,
                offset_seconds=chat_config.ATTACHMENT_POSTER_OFFSET_SECONDS,
                max_side=chat_config.ATTACHMENT_POSTER_MAX_SIDE,
                hdr=stream.is_hdr,
            )
            rendered = await self.image_renderer.render_frame(attachment, poster)
        except (MediaTranscodeError, AttachmentMediaValidationError) as exc:
            if isinstance(exc, MediaTranscodeError) and not exc.permanent:
                raise
            ATTACHMENT_MEDIA_DEGRADED.labels(stage="poster").inc()
            logger.warning(
                "Video poster could not be extracted, sending without a preview",
                extra={"slot_id": str(attachment.id), "error": str(exc)},
            )
        else:
            previews = await self._upload_previews(attachment, rendered)
            thumbhash = rendered.thumbhash

        if original is source:
            await self._copy_original(attachment, stat)
        else:
            await self._upload_original(attachment, original)

        attachment.apply_media(width=None, height=None, previews=previews, thumbhash=thumbhash)

    async def _strip_video_metadata(
        self, attachment: MessageAttachment, source: Path, workdir: Path
    ) -> Path:
        container = VIDEO_CONTAINERS.get(attachment.mime_type)
        if attachment.attachment_type != AttachmentType.VIDEO or container is None:
            return source

        cleaned = workdir / f"clean.{container}"
        try:
            await self.media_transcoder.strip_metadata(source, cleaned, container=container)
        except MediaTranscodeError as exc:
            if not exc.permanent:
                raise
            ATTACHMENT_MEDIA_DEGRADED.labels(stage="remux").inc()
            logger.warning(
                "Video metadata could not be stripped, keeping the uploaded bytes",
                extra={"slot_id": str(attachment.id), "error": str(exc)},
            )
            return source
        return cleaned

    async def _upload_previews(
        self, attachment: MessageAttachment, media: RenderedMedia
    ) -> list[dict[str, Any]]:
        extension = self.image_renderer.preview_extension
        mime_type = self.image_renderer.preview_mime_type
        keys = [
            AttachmentStorageKeys.preview(attachment.chat_id, attachment.id, preview.size, extension)
            for preview in media.previews
        ]
        await asyncio.gather(*(
            self.storage_service.upload_file(
                UploadFile(
                    bucket_name=chat_config.ATTACHMENT_BUCKET,
                    file_key=key,
                    file_content=io.BytesIO(preview.content),
                    size=len(preview.content),
                    content_type=mime_type,
                )
            )
            for key, preview in zip(keys, media.previews, strict=True)
        ))
        return [
            {
                "size": preview.size,
                "width": preview.width,
                "height": preview.height,
                "s3_key": key,
                "mime_type": mime_type,
                "file_size": len(preview.content),
            }
            for key, preview in zip(keys, media.previews, strict=True)
        ]

    async def _upload_original(self, attachment: MessageAttachment, path: Path) -> None:
        size = path.stat().st_size
        with path.open("rb") as content:
            await self.storage_service.upload_file(
                UploadFile(
                    bucket_name=chat_config.ATTACHMENT_BUCKET,
                    file_key=attachment.s3_key,
                    file_content=content,
                    size=size,
                    content_type=attachment.mime_type,
                )
            )
        attachment.replace_original(size)

    async def _copy_original(self, attachment: MessageAttachment, stat: ObjectStat) -> None:
        await self.storage_service.copy_object(
            bucket_from=chat_config.ATTACHMENT_BUCKET_PENDING,
            file_key_from=attachment.s3_key,
            bucket_to=chat_config.ATTACHMENT_BUCKET,
            file_key_to=attachment.s3_key,
            source_stat=stat,
        )
