import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyvips  # type: ignore[import-untyped]

from app.chats.config import chat_config
from app.chats.exceptions import AttachmentMediaValidationError, AttachmentRejectionReason
from app.chats.models.attachment import MessageAttachment
from app.core.services.media.thumbhash import (
    MAX_SIDE as THUMBHASH_MAX_SIDE,
    encode_thumbhash,
)

SANITIZED_FORMATS: dict[str, tuple[str, str]] = {
    "image/jpeg": ("image/jpeg", "jpg"),
    "image/png": ("image/png", "png"),
    "image/webp": ("image/webp", "webp"),
    "image/heic": ("image/jpeg", "jpg"),
    "image/heif": ("image/jpeg", "jpg"),
}

PASSTHROUGH_MIMES = frozenset({"image/gif"})

PREVIEW_MIME_TYPES: dict[str, str] = {
    "webp": "image/webp",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "avif": "image/avif",
}


@dataclass(frozen=True)
class RenderedPreview:
    size: int
    width: int
    height: int
    content: bytes


@dataclass(frozen=True)
class RenderedMedia:
    width: int
    height: int
    previews: tuple[RenderedPreview, ...]
    thumbhash: str


@dataclass(frozen=True)
class SanitizedImage:
    path: Path
    mime_type: str
    extension: str


@dataclass(frozen=True)
class RenderedPhoto:
    width: int
    height: int
    media: RenderedMedia
    original: SanitizedImage | None


@dataclass
class AttachmentImageRenderer:

    @property
    def preview_extension(self) -> str:
        return chat_config.ATTACHMENT_PREVIEW_FORMAT

    @property
    def preview_mime_type(self) -> str:
        return PREVIEW_MIME_TYPES.get(self.preview_extension, "application/octet-stream")

    async def render_photo(
        self, attachment: MessageAttachment, source: Path, workdir: Path
    ) -> RenderedPhoto:
        return await asyncio.to_thread(self._render_photo, attachment, source, workdir)

    async def render_frame(self, attachment: MessageAttachment, frame: Path) -> RenderedMedia:
        return await asyncio.to_thread(self._render_previews, attachment, frame)

    def _render_photo(
        self, attachment: MessageAttachment, source: Path, workdir: Path
    ) -> RenderedPhoto:
        header = self._open(attachment, source)
        width, height = int(header.width), int(header.height)
        if width <= 0 or height <= 0 or width * height > chat_config.ATTACHMENT_IMAGE_MAX_PIXELS:
            raise self._rejection(
                attachment,
                AttachmentRejectionReason.RESOLUTION_LIMIT_EXCEEDED,
                limit=chat_config.ATTACHMENT_IMAGE_MAX_PIXELS,
                detected={"width": width, "height": height},
            )

        original: SanitizedImage | None = None
        if attachment.mime_type not in PASSTHROUGH_MIMES:
            original = self._sanitize(attachment, header, source, workdir)
            sanitized = self._open(attachment, original.path)
            width, height = int(sanitized.width), int(sanitized.height)

        media = self._render_previews(attachment, original.path if original else source)
        return RenderedPhoto(width=width, height=height, media=media, original=original)

    def _sanitize(
        self, attachment: MessageAttachment, header: Any, source: Path, workdir: Path
    ) -> SanitizedImage:
        formats = SANITIZED_FORMATS.get(attachment.mime_type)
        if formats is None:
            raise self._rejection(attachment, AttachmentRejectionReason.INVALID_MEDIA)
        mime_type, extension = formats

        fields = set(header.get_fields())
        orientation = int(header.get("orientation")) if "orientation" in fields else 1
        pages = int(header.get("n-pages")) if "n-pages" in fields else 1
        animated = pages > 1 and extension == "webp"
        rotate = orientation != 1 and not animated

        options: dict[str, Any] = {"access": "random" if rotate else "sequential"}
        if animated:
            options["n"] = -1

        try:
            image = pyvips.Image.new_from_file(str(source), **options)
            if rotate:
                image = image.autorot()
            if extension == "jpg" and image.hasalpha():
                image = image.flatten(background=[255, 255, 255])

            target = workdir / f"original.{extension}"
            image.write_to_file(str(target), **self._original_options(extension))
        except pyvips.Error as exc:
            raise self._rejection(attachment, AttachmentRejectionReason.INVALID_MEDIA) from exc

        return SanitizedImage(path=target, mime_type=mime_type, extension=extension)

    def _render_previews(self, attachment: MessageAttachment, source: Path) -> RenderedMedia:
        sizes = sorted(set(chat_config.ATTACHMENT_PREVIEW_SIZES))
        try:
            base = pyvips.Image.thumbnail(
                str(source), sizes[-1], height=sizes[-1], size="down"
            ).copy_memory()
            base_long_side = max(int(base.width), int(base.height))

            previews: list[RenderedPreview] = []
            for size in sizes:
                image = base if size >= base_long_side else base.thumbnail_image(size, height=size)
                previews.append(
                    RenderedPreview(
                        size=size,
                        width=int(image.width),
                        height=int(image.height),
                        content=self._encode_preview(image),
                    )
                )
                if size >= base_long_side:
                    break

            thumbhash = self._thumbhash(base)
        except pyvips.Error as exc:
            raise self._rejection(attachment, AttachmentRejectionReason.INVALID_MEDIA) from exc

        return RenderedMedia(
            width=int(base.width),
            height=int(base.height),
            previews=tuple(previews),
            thumbhash=thumbhash,
        )

    def _encode_preview(self, image: Any) -> bytes:
        if self.preview_extension in ("jpg", "jpeg") and image.hasalpha():
            image = image.flatten(background=[255, 255, 255])
        return image.write_to_buffer(
            f".{self.preview_extension}",
            Q=chat_config.ATTACHMENT_PREVIEW_QUALITY,
            keep=pyvips.enums.ForeignKeep.NONE,
        )

    @staticmethod
    def _thumbhash(image: Any) -> str:
        small = image.thumbnail_image(THUMBHASH_MAX_SIDE, height=THUMBHASH_MAX_SIDE)
        if small.interpretation != "srgb":
            small = small.colourspace("srgb")
        if small.format != "uchar":
            small = small.cast("uchar")
        if small.bands == 3:
            small = small.bandjoin(255)
        return encode_thumbhash(int(small.width), int(small.height), bytes(small.write_to_memory()))

    @staticmethod
    def _original_options(extension: str) -> dict[str, Any]:
        keep = pyvips.enums.ForeignKeep.ICC
        if extension == "jpg":
            return {
                "Q": chat_config.ATTACHMENT_ORIGINAL_QUALITY,
                "optimize_coding": True,
                "interlace": True,
                "subsample_mode": "on",
                "keep": keep,
            }
        if extension == "webp":
            return {"Q": chat_config.ATTACHMENT_ORIGINAL_QUALITY, "keep": keep}
        return {"keep": keep}

    def _open(self, attachment: MessageAttachment, source: Path) -> Any:
        try:
            return pyvips.Image.new_from_file(str(source))
        except pyvips.Error as exc:
            raise self._rejection(attachment, AttachmentRejectionReason.INVALID_MEDIA) from exc

    @staticmethod
    def _rejection(
        attachment: MessageAttachment,
        reason: AttachmentRejectionReason,
        *,
        limit: int | None = None,
        detected: dict[str, Any] | None = None,
    ) -> AttachmentMediaValidationError:
        return AttachmentMediaValidationError(
            reason=reason,
            attachment_id=str(attachment.id),
            attachment_type=attachment.attachment_type.value,
            limit=limit,
            detected=detected,
        )
