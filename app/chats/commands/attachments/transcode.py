import logging
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.keys import AttachmentKeys, AttachmentStorageKeys
from app.chats.metrics import ATTACHMENT_TRANSCODE_RESULTS, ATTACHMENT_TRANSCODE_SECONDS
from app.chats.models.attachment import AttachmentType, HlsStatus
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.services.attachment_media import AttachmentMediaValidator
from app.chats.services.hls import MASTER_PLAYLIST, master_playlist, plan_renditions
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.media.dtos import HlsJob
from app.core.services.media.exceptions import MediaProbeError, MediaTranscodeError
from app.core.services.media.service import MediaProbeService, MediaTranscoder
from app.core.services.storage.dtos import UploadFile
from app.core.services.storage.exceptions import ObjectNotFoundError, StorageError
from app.core.services.storage.service import StorageService

logger = logging.getLogger(__name__)


RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class PermanentTranscodeError(Exception):
    pass


@dataclass(frozen=True)
class TranscodeAttachmentCommand(BaseCommand):
    attachment_id: str


@dataclass(frozen=True)
class TranscodeAttachmentCommandHandler(BaseCommandHandler[TranscodeAttachmentCommand, None]):
    session: AsyncSession
    attachment_repository: AttachmentRepository
    storage_service: StorageService
    media_probe_service: MediaProbeService
    media_transcoder: MediaTranscoder
    redis: Redis

    async def handle(self, command: TranscodeAttachmentCommand) -> None:
        lock_key = AttachmentKeys.transcode_lock(command.attachment_id)
        token = uuid4().hex
        lock_ttl = chat_config.VIDEO_TRANSCODE_TIMEOUT_SECONDS + 300
        if not await self.redis.set(lock_key, token, nx=True, ex=lock_ttl):
            ATTACHMENT_TRANSCODE_RESULTS.labels(result="locked").inc()
            logger.info("HLS transcode already running", extra={"attachment_id": command.attachment_id})
            return

        try:
            await self._transcode(UUID(command.attachment_id))
        finally:
            await self.redis.eval(RELEASE_LOCK_SCRIPT, 1, lock_key, token)  # type: ignore[misc]

    async def _transcode(self, attachment_id: UUID) -> None:
        attachment = await self.attachment_repository.get_by_id(attachment_id)
        if (
            attachment is None
            or attachment.attachment_type != AttachmentType.VIDEO
            or attachment.hls_status != HlsStatus.PENDING
        ):
            ATTACHMENT_TRANSCODE_RESULTS.labels(result="skipped").inc()
            return

        if attachment.hls_attempts >= chat_config.VIDEO_TRANSCODE_MAX_ATTEMPTS:
            await self._finish(attachment_id, HlsStatus.FAILED, None, "failed")
            return

        attachment.start_hls_attempt()
        s3_key, hls_dir = attachment.s3_key, AttachmentStorageKeys.hls_dir(attachment.chat_id, attachment.id)
        attempt = attachment.hls_attempts
        await self.session.commit()

        started = time.monotonic()
        try:
            with TemporaryDirectory(prefix=f"transcode-{attachment_id}-") as tmp_dir:
                await self._render(Path(tmp_dir), s3_key, hls_dir)
        except PermanentTranscodeError as exc:
            logger.warning(
                "HLS transcode failed permanently",
                extra={"attachment_id": str(attachment_id), "attempt": attempt, "error": str(exc)},
            )
            await self._finish(attachment_id, HlsStatus.FAILED, None, "failed")
            return
        except (StorageError, MediaProbeError, MediaTranscodeError):
            logger.exception(
                "HLS transcode hit an infrastructure error, the sweeper will retry it",
                extra={"attachment_id": str(attachment_id), "attempt": attempt},
            )
            ATTACHMENT_TRANSCODE_RESULTS.labels(result="retry").inc()
            return
        finally:
            ATTACHMENT_TRANSCODE_SECONDS.observe(time.monotonic() - started)

        await self._finish(attachment_id, HlsStatus.READY, f"{hls_dir}/{MASTER_PLAYLIST}", "ready")
        logger.info(
            "HLS transcode finished",
            extra={"attachment_id": str(attachment_id), "seconds": round(time.monotonic() - started, 3)},
        )

    async def _render(self, workdir: Path, s3_key: str, hls_dir: str) -> None:
        source = workdir / "source"
        output = workdir / "hls"
        output.mkdir()

        try:
            await self.storage_service.download_to_path(
                bucket_name=chat_config.ATTACHMENT_BUCKET,
                file_key=s3_key,
                destination=source,
                max_bytes=chat_config.MAX_MEDIA_SIZE,
            )
            media_info = await self.media_probe_service.probe(source)
        except ObjectNotFoundError as exc:
            raise PermanentTranscodeError("source object is gone") from exc
        except MediaProbeError as exc:
            if exc.permanent:
                raise PermanentTranscodeError(str(exc)) from exc
            raise

        if not media_info.video_streams:
            raise PermanentTranscodeError("no video stream")

        stream = media_info.video_streams[0]
        width, height = AttachmentMediaValidator.display_size(stream)
        if width <= 0 or height <= 0:
            raise PermanentTranscodeError("video dimensions are unknown")

        renditions = plan_renditions(width, height)
        has_audio = bool(media_info.audio_streams)
        job = HlsJob(
            renditions=renditions,
            has_audio=has_audio,
            hdr=stream.is_hdr,
            segment_seconds=chat_config.VIDEO_HLS_SEGMENT_SECONDS,
            crf=chat_config.VIDEO_HLS_CRF,
            preset=chat_config.VIDEO_HLS_PRESET,
            max_fps=chat_config.VIDEO_HLS_MAX_FPS,
        )

        try:
            await self.media_transcoder.transcode_hls(source, output, job)
        except MediaTranscodeError as exc:
            if exc.permanent:
                raise PermanentTranscodeError(str(exc)) from exc
            raise

        (output / MASTER_PLAYLIST).write_text(master_playlist(renditions, has_audio=has_audio))

        # Мастер — последним: пока его нет в бакете, ссылку на поток никто не получит.
        uploads = [*(f"{r.name}.mp4" for r in renditions), *(f"{r.name}.m3u8" for r in renditions)]
        for name in [*uploads, MASTER_PLAYLIST]:
            await self._upload(output / name, f"{hls_dir}/{name}")

    async def _upload(self, path: Path, key: str) -> None:
        content_type = "application/vnd.apple.mpegurl" if path.suffix == ".m3u8" else "video/mp4"
        with path.open("rb") as content:
            await self.storage_service.upload_file(
                UploadFile(
                    bucket_name=chat_config.ATTACHMENT_BUCKET,
                    file_key=key,
                    file_content=content,
                    size=path.stat().st_size,
                    content_type=content_type,
                )
            )

    async def _finish(self, root_id: UUID, status: HlsStatus, hls_key: str | None, result: str) -> None:
        await self.attachment_repository.set_hls_state(root_id, status, hls_key)
        await self.session.commit()
        ATTACHMENT_TRANSCODE_RESULTS.labels(result=result).inc()
