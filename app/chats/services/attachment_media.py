import logging
import math
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.chats.config import chat_config
from app.chats.exceptions import AttachmentMediaValidationError, AttachmentRejectionReason
from app.chats.models.attachment import AttachmentType, MessageAttachment
from app.core.services.media.dtos import MediaInfo
from app.core.services.media.exceptions import (
    InvalidMediaError,
    MediaMetadataUnreadableError,
    MediaProbeError,
    MediaProbeTimeoutError,
)
from app.core.services.media.service import MediaProbeService
from app.core.services.storage.dtos import ObjectStat
from app.core.services.storage.exceptions import ObjectTooLargeError
from app.core.services.storage.service import StorageService

logger = logging.getLogger(__name__)

PROBE_REASON_MAP: dict[type[MediaProbeError], AttachmentRejectionReason] = {
    MediaProbeTimeoutError: AttachmentRejectionReason.PROBE_TIMEOUT,
    MediaMetadataUnreadableError: AttachmentRejectionReason.METADATA_UNREADABLE,
    InvalidMediaError: AttachmentRejectionReason.INVALID_MEDIA,
}

SIZE_LIMITS: dict[AttachmentType, int] = {
    AttachmentType.VOICE: chat_config.MAX_VOICE_SIZE,
    AttachmentType.VIDEO_NOTE: chat_config.MAX_VIDEO_NOTE_SIZE,
}

DURATION_LIMITS: dict[AttachmentType, int] = {
    AttachmentType.VOICE: chat_config.MAX_VOICE_DURATION_SECONDS,
    AttachmentType.VIDEO_NOTE: chat_config.MAX_VIDEO_NOTE_DURATION_SECONDS,
}


@dataclass
class AttachmentMediaValidator:
    storage_service: StorageService
    media_probe_service: MediaProbeService

    @staticmethod
    def requires_probe(attachment_type: AttachmentType) -> bool:
        return attachment_type in SIZE_LIMITS

    async def validate_and_apply(self, attachment: MessageAttachment, stat: ObjectStat) -> MediaInfo:
        attachment_type = attachment.attachment_type
        max_bytes = SIZE_LIMITS[attachment_type]

        if stat.size <= 0:
            raise AttachmentMediaValidationError(
                reason=AttachmentRejectionReason.INVALID_MEDIA,
                attachment_id=str(attachment.id),
                attachment_type=attachment.attachment_type.value,
                detected={"size": stat.size},
            )

        if stat.size > max_bytes:
            raise AttachmentMediaValidationError(
                reason=AttachmentRejectionReason.SIZE_LIMIT_EXCEEDED,
                attachment_id=str(attachment.id),
                attachment_type=attachment.attachment_type.value,
                limit=max_bytes,
                detected={"size": stat.size},
            )

        media_info = await self._probe(attachment, stat, max_bytes)

        if attachment_type == AttachmentType.VOICE:
            self._validate_voice(attachment, media_info)
        else:
            self._validate_video_note(attachment, media_info)

        limit = DURATION_LIMITS[attachment.attachment_type]
        duration_seconds = min(limit, max(1, round(media_info.duration)))

        attachment.set_duration(duration_seconds)

        if attachment.attachment_type == AttachmentType.VIDEO_NOTE:
            stream = media_info.video_streams[0]
            attachment.set_resolution(int(stream.width or 0), int(stream.height or 0))

        return media_info

    async def _probe(self, attachment: MessageAttachment, stat: ObjectStat, max_bytes: int) -> MediaInfo:
        with TemporaryDirectory(prefix=f"attachment-{attachment.id}-") as tmp_dir:
            local_path = Path(tmp_dir) / "media"

            try:
                await self.storage_service.download_to_path(
                    bucket_name=chat_config.ATTACHMENT_BUCKET_PENDING,
                    file_key=attachment.s3_key,
                    destination=local_path,
                    max_bytes=max_bytes,
                    stat=stat,
                )
            except ObjectTooLargeError:
                raise AttachmentMediaValidationError(
                    reason=AttachmentRejectionReason.SIZE_LIMIT_EXCEEDED,
                    attachment_id=str(attachment.id),
                    attachment_type=attachment.attachment_type.value,
                    limit=max_bytes,
                )

            try:
                return await self.media_probe_service.probe(local_path)
            except MediaProbeError as exc:
                if not exc.permanent:
                    raise

                raise AttachmentMediaValidationError(
                    reason=PROBE_REASON_MAP.get(type(exc), AttachmentRejectionReason.INVALID_MEDIA),
                    attachment_id=str(attachment.id),
                    attachment_type=attachment.attachment_type.value,
                )

    def _validate_voice(self, attachment: MessageAttachment, media_info: MediaInfo) -> None:
        if not media_info.audio_streams or media_info.video_streams:
            raise AttachmentMediaValidationError(
                reason=AttachmentRejectionReason.INVALID_MEDIA,
                attachment_id=str(attachment.id),
                attachment_type=attachment.attachment_type.value,
                detected={
                    "audio_streams": len(media_info.audio_streams),
                    "video_streams": len(media_info.video_streams),
                },
            )

        self._validate_duration(attachment, media_info)

    def _validate_video_note(self, attachment: MessageAttachment, media_info: MediaInfo) -> None:
        video_streams = media_info.video_streams

        if len(video_streams) != 1:
            raise AttachmentMediaValidationError(
                reason=AttachmentRejectionReason.INVALID_MEDIA,
                attachment_id=str(attachment.id),
                attachment_type=attachment.attachment_type.value,
                detected={"video_streams": len(video_streams)},
            )

        self._validate_duration(attachment, media_info)

        stream = video_streams[0]
        width, height = stream.width, stream.height

        if width is None or height is None or width <= 0 or height <= 0:
            raise AttachmentMediaValidationError(
                reason=AttachmentRejectionReason.METADATA_UNREADABLE,
                attachment_id=str(attachment.id),
                attachment_type=attachment.attachment_type.value,
                detected={"width": width, "height": height},
            )

        if max(width, height) > chat_config.MAX_VIDEO_NOTE_RESOLUTION_PX:
            raise AttachmentMediaValidationError(
                reason=AttachmentRejectionReason.RESOLUTION_LIMIT_EXCEEDED,
                attachment_id=str(attachment.id),
                attachment_type=attachment.attachment_type.value,
                limit=chat_config.MAX_VIDEO_NOTE_RESOLUTION_PX,
                detected={"width": width, "height": height},
            )

        if stream.frame_rate is not None and stream.frame_rate > chat_config.MAX_VIDEO_NOTE_FPS:
            raise AttachmentMediaValidationError(
                reason=AttachmentRejectionReason.FRAME_RATE_LIMIT_EXCEEDED,
                attachment_id=str(attachment.id),
                attachment_type=attachment.attachment_type.value,
                limit=chat_config.MAX_VIDEO_NOTE_FPS,
                detected={"frame_rate": round(stream.frame_rate, 3)},
            )

    def _validate_duration(self, attachment: MessageAttachment, media_info: MediaInfo) -> None:
        duration = media_info.duration
        limit = DURATION_LIMITS[attachment.attachment_type]

        if not math.isfinite(duration) or duration <= 0:
            raise AttachmentMediaValidationError(
                reason=AttachmentRejectionReason.METADATA_UNREADABLE,
                attachment_id=str(attachment.id),
                attachment_type=attachment.attachment_type.value,
                detected={"duration": duration},
            )

        if duration > limit:
            raise AttachmentMediaValidationError(
                reason=AttachmentRejectionReason.DURATION_LIMIT_EXCEEDED,
                attachment_id=str(attachment.id),
                attachment_type=attachment.attachment_type.value,
                limit=limit,
                detected={"duration": round(duration, 3)},
            )
