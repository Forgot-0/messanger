import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.metrics import ATTACHMENT_TRANSCODE_RESULTS
from app.chats.models.attachment import HlsStatus
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.tasks.transcode_attachment import AttachmentTranscodeTask
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.queues.service import QueueService
from app.core.utils import now_utc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepStaleTranscodesCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class SweepStaleTranscodesCommandHandler(BaseCommandHandler[SweepStaleTranscodesCommand, int]):
    session: AsyncSession
    attachment_repository: AttachmentRepository
    queue_service: QueueService

    async def handle(self, command: SweepStaleTranscodesCommand) -> int:  # noqa: ARG002
        threshold = now_utc() - timedelta(seconds=chat_config.VIDEO_TRANSCODE_STALE_AFTER_SECONDS)
        stale = await self.attachment_repository.find_stale_transcodes(
            threshold, chat_config.VIDEO_TRANSCODE_SWEEP_BATCH_SIZE
        )
        if not stale:
            return 0

        retry = [item.id for item in stale if item.hls_attempts < chat_config.VIDEO_TRANSCODE_MAX_ATTEMPTS]
        exhausted = [item.id for item in stale if item.hls_attempts >= chat_config.VIDEO_TRANSCODE_MAX_ATTEMPTS]

        for root_id in exhausted:
            await self.attachment_repository.set_hls_state(root_id, HlsStatus.FAILED, None)
        await self.attachment_repository.touch(retry)
        await self.session.commit()

        ATTACHMENT_TRANSCODE_RESULTS.labels(result="failed").inc(len(exhausted))
        for attachment_id in retry:
            try:
                await self.queue_service.push(AttachmentTranscodeTask, data={"attachment_id": str(attachment_id)})
            except Exception:
                logger.exception("Failed to re-enqueue HLS transcode", extra={"attachment_id": str(attachment_id)})

        logger.info(
            "Stale HLS transcodes swept",
            extra={"requeued": len(retry), "failed": len(exhausted)},
        )
        return len(stale)
