from datetime import timedelta
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.attachments.sweep_transcodes import (
    SweepStaleTranscodesCommand,
    SweepStaleTranscodesCommandHandler,
)
from app.chats.commands.attachments.transcode import (
    TranscodeAttachmentCommand,
    TranscodeAttachmentCommandHandler,
)
from app.chats.config import chat_config
from app.chats.keys import AttachmentKeys
from app.chats.models.attachment import AttachmentType, HlsStatus, MessageAttachment
from app.chats.models.chat import Chat
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.tasks.transcode_attachment import AttachmentTranscodeTask
from app.core.services.media.exceptions import MediaTranscodeFailedError, MediaTranscodeUnavailableError
from app.core.services.storage.aioboto.client import S3Client
from app.core.services.storage.service import StorageService
from app.core.utils import now_utc
from tests.mocks import FakeQueueService
from tests.support.media import FakeMediaProbe, FakeMediaTranscoder, video_info


async def read_text(storage: StorageService, key: str) -> str:
    stat = await storage.get_stat(chat_config.ATTACHMENT_BUCKET, key)
    data = await storage.download_bytes(chat_config.ATTACHMENT_BUCKET, key, max_bytes=stat.size, stat=stat)
    return data.decode()


async def make_video(
    db_session: AsyncSession,
    s3_test_client: S3Client,
    chat: Chat,
    *,
    hls_status: HlsStatus | None = HlsStatus.PENDING,
    attempts: int = 0,
    upload: bool = True,
) -> MessageAttachment:
    video = MessageAttachment.create(
        chat_id=chat.id,
        uploader_id=1,
        attachment_type=AttachmentType.VIDEO,
        s3_key=f"chats/{chat.id}/{uuid4()}/clip.mp4",
        mime_type="video/mp4",
        original_filename="clip.mp4",
        size=16,
    )
    video.mark_proccesed()
    video.set_resolution(1920, 1080)
    video.set_duration(12)
    video.hls_status = hls_status
    video.hls_attempts = attempts
    db_session.add(video)
    await db_session.commit()
    if upload:
        await s3_test_client.put_object(Bucket=chat_config.ATTACHMENT_BUCKET, Key=video.s3_key, Body=b"v" * 16)
    return video


async def reload(repository: AttachmentRepository, attachment: MessageAttachment) -> MessageAttachment:
    (fresh,) = await repository.get_by_ids([attachment.id])
    await repository.session.refresh(fresh)
    return fresh


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestTranscodeAttachment:

    @pytest.fixture
    def transcoder(self) -> FakeMediaTranscoder:
        return FakeMediaTranscoder()

    @pytest.fixture
    def probe(self) -> FakeMediaProbe:
        return FakeMediaProbe(media_info=video_info(width=1920, height=1080))

    @pytest.fixture
    def handler(
        self,
        db_session: AsyncSession,
        attachment_repository: AttachmentRepository,
        storage_service: StorageService,
        redis_client: Redis,
        probe: FakeMediaProbe,
        transcoder: FakeMediaTranscoder,
    ) -> TranscodeAttachmentCommandHandler:
        return TranscodeAttachmentCommandHandler(
            session=db_session,
            attachment_repository=attachment_repository,
            storage_service=storage_service,
            media_probe_service=probe,
            media_transcoder=transcoder,
            redis=redis_client,
        )

    async def test_ready_stream_is_published_to_the_root_and_every_forward(
        self, handler, attachment_repository, db_session, storage_service, s3_test_client, group_chat, transcoder,
    ) -> None:
        root = await make_video(db_session, s3_test_client, group_chat)
        forward = root.create_for_forward(chat_id=uuid4())
        forward_of_forward = forward.create_for_forward(chat_id=uuid4())
        db_session.add_all([forward, forward_of_forward])
        await db_session.commit()

        await handler.handle(TranscodeAttachmentCommand(attachment_id=str(root.id)))

        hls_key = f"media/{group_chat.id}/{root.id}/hls/master.m3u8"
        for attachment in (root, forward, forward_of_forward):
            fresh = await reload(attachment_repository, attachment)
            assert (fresh.hls_status, fresh.hls_key) == (HlsStatus.READY, hls_key)

        (job,) = transcoder.hls_jobs
        assert [(r.width, r.height) for r in job.renditions] == [(640, 360), (1280, 720), (1920, 1080)]
        master = await read_text(storage_service, hls_key)
        assert master.count("#EXT-X-STREAM-INF") == 3
        variant = await read_text(storage_service, f"media/{group_chat.id}/{root.id}/hls/v2.m3u8")
        assert "v2.mp4" in variant

    async def test_attempt_is_counted_before_the_work_starts(
        self, handler, attachment_repository, db_session, s3_test_client, group_chat, transcoder,
    ) -> None:
        video = await make_video(db_session, s3_test_client, group_chat, attempts=1)
        transcoder.hls_error = MediaTranscodeUnavailableError()

        await handler.handle(TranscodeAttachmentCommand(attachment_id=str(video.id)))

        fresh = await reload(attachment_repository, video)
        assert fresh.hls_attempts == 2
        assert fresh.hls_status is HlsStatus.PENDING

    async def test_permanent_failure_marks_the_stream_failed(
        self, handler, attachment_repository, db_session, s3_test_client, group_chat, transcoder,
    ) -> None:
        video = await make_video(db_session, s3_test_client, group_chat)
        transcoder.hls_error = MediaTranscodeFailedError()

        await handler.handle(TranscodeAttachmentCommand(attachment_id=str(video.id)))

        assert (await reload(attachment_repository, video)).hls_status is HlsStatus.FAILED

    async def test_missing_source_is_a_permanent_failure(
        self, handler, attachment_repository, db_session, s3_test_client, group_chat, transcoder,
    ) -> None:
        video = await make_video(db_session, s3_test_client, group_chat, upload=False)

        await handler.handle(TranscodeAttachmentCommand(attachment_id=str(video.id)))

        assert (await reload(attachment_repository, video)).hls_status is HlsStatus.FAILED
        assert transcoder.hls_jobs == []

    async def test_exhausted_attempts_fail_without_transcoding(
        self, handler, attachment_repository, db_session, s3_test_client, group_chat, transcoder,
    ) -> None:
        video = await make_video(
            db_session, s3_test_client, group_chat, attempts=chat_config.VIDEO_TRANSCODE_MAX_ATTEMPTS
        )

        await handler.handle(TranscodeAttachmentCommand(attachment_id=str(video.id)))

        assert (await reload(attachment_repository, video)).hls_status is HlsStatus.FAILED
        assert transcoder.calls == []

    @pytest.mark.parametrize("status", [HlsStatus.READY, HlsStatus.FAILED, None])
    async def test_only_pending_streams_are_transcoded(
        self, handler, db_session, s3_test_client, group_chat, transcoder, status,
    ) -> None:
        video = await make_video(db_session, s3_test_client, group_chat, hls_status=status)

        await handler.handle(TranscodeAttachmentCommand(attachment_id=str(video.id)))

        assert transcoder.calls == []

    async def test_running_transcode_is_not_started_twice(
        self, handler, attachment_repository, db_session, s3_test_client, group_chat, transcoder, redis_client,
    ) -> None:
        video = await make_video(db_session, s3_test_client, group_chat)
        await redis_client.set(AttachmentKeys.transcode_lock(str(video.id)), "other-worker", ex=60)

        await handler.handle(TranscodeAttachmentCommand(attachment_id=str(video.id)))

        assert transcoder.calls == []
        assert (await reload(attachment_repository, video)).hls_attempts == 0
        assert await redis_client.get(AttachmentKeys.transcode_lock(str(video.id))) == "other-worker"

    async def test_lock_is_released_after_the_run(
        self, handler, db_session, s3_test_client, group_chat, redis_client,
    ) -> None:
        video = await make_video(db_session, s3_test_client, group_chat)

        await handler.handle(TranscodeAttachmentCommand(attachment_id=str(video.id)))

        assert await redis_client.get(AttachmentKeys.transcode_lock(str(video.id))) is None


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestSweepStaleTranscodes:

    @pytest.fixture
    def queue(self) -> FakeQueueService:
        return FakeQueueService()

    @pytest.fixture
    def handler(
        self, db_session: AsyncSession, attachment_repository: AttachmentRepository, queue: FakeQueueService,
    ) -> SweepStaleTranscodesCommandHandler:
        return SweepStaleTranscodesCommandHandler(
            session=db_session, attachment_repository=attachment_repository, queue_service=queue,
        )

    async def _age(self, db_session: AsyncSession, attachment: MessageAttachment, seconds: int) -> None:
        await db_session.execute(
            update(MessageAttachment)
            .where(MessageAttachment.id == attachment.id)
            .values(updated_at=now_utc() - timedelta(seconds=seconds))
        )
        await db_session.commit()

    async def test_lost_transcode_is_requeued_and_touched(
        self, handler, queue, attachment_repository, db_session, s3_test_client, group_chat,
    ) -> None:
        stale = await make_video(db_session, s3_test_client, group_chat, attempts=1)
        fresh = await make_video(db_session, s3_test_client, group_chat)
        await self._age(db_session, stale, chat_config.VIDEO_TRANSCODE_STALE_AFTER_SECONDS + 60)

        await handler.handle(SweepStaleTranscodesCommand())

        assert queue.pushed == [(AttachmentTranscodeTask, {"attachment_id": str(stale.id)})]
        touched = await reload(attachment_repository, stale)
        assert touched.updated_at > now_utc() - timedelta(minutes=1)
        assert (await reload(attachment_repository, fresh)).hls_status is HlsStatus.PENDING

    async def test_exhausted_transcode_is_failed_with_its_forwards(
        self, handler, queue, attachment_repository, db_session, s3_test_client, group_chat,
    ) -> None:
        root = await make_video(
            db_session, s3_test_client, group_chat, attempts=chat_config.VIDEO_TRANSCODE_MAX_ATTEMPTS
        )
        forward = root.create_for_forward(chat_id=uuid4())
        db_session.add(forward)
        await db_session.commit()
        await self._age(db_session, root, chat_config.VIDEO_TRANSCODE_STALE_AFTER_SECONDS + 60)
        await self._age(db_session, forward, chat_config.VIDEO_TRANSCODE_STALE_AFTER_SECONDS + 60)

        await handler.handle(SweepStaleTranscodesCommand())

        assert queue.pushed == []
        assert (await reload(attachment_repository, root)).hls_status is HlsStatus.FAILED
        assert (await reload(attachment_repository, forward)).hls_status is HlsStatus.FAILED

    async def test_forwarded_copies_are_never_enqueued_themselves(
        self, handler, queue, db_session, s3_test_client, group_chat,
    ) -> None:
        root = await make_video(db_session, s3_test_client, group_chat)
        forward = root.create_for_forward(chat_id=uuid4())
        db_session.add(forward)
        await db_session.commit()
        await self._age(db_session, root, chat_config.VIDEO_TRANSCODE_STALE_AFTER_SECONDS + 60)
        await self._age(db_session, forward, chat_config.VIDEO_TRANSCODE_STALE_AFTER_SECONDS + 60)

        await handler.handle(SweepStaleTranscodesCommand())

        assert queue.pushed == [(AttachmentTranscodeTask, {"attachment_id": str(root.id)})]
