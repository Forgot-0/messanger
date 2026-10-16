import base64
from uuid import uuid4

import magic
import pytest
import pyvips  # type: ignore[import-untyped]
from dishka import AsyncContainer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.attachments.proccess import (
    ProccessAttachmentsCommand,
    ProccessAttachmentsCommandHandler,
)
from app.chats.config import chat_config
from app.chats.models.attachment import (
    AttachmentStatus,
    AttachmentType,
    MessageAttachment,
)
from app.chats.models.chat import Chat
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.services.attachment_images import AttachmentImageRenderer
from app.chats.services.attachment_media import AttachmentMediaValidator
from app.chats.services.attachment_processor import AttachmentMediaProcessor
from app.core.services.media.exceptions import MediaTranscodeFailedError, MediaTranscodeUnavailableError
from app.core.services.storage.aioboto.client import S3Client
from app.core.services.storage.exceptions import ObjectNotFoundError
from app.core.services.storage.service import StorageService
from app.core.websocket.manager import ConnectionManager
from app.core.websocket.presence import PresenceService
from tests.chats.integration.conftest import GATEWAY_ID
from tests.support.media import (
    GPS_LATITUDE,
    FakeMediaProbe,
    FakeMediaTranscoder,
    make_gif,
    make_jpeg,
    make_png,
    video_info,
)

MP4_BYTES = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 256


async def read_object(storage: StorageService, key: str) -> bytes:
    stat = await storage.get_stat(chat_config.ATTACHMENT_BUCKET, key)
    return await storage.download_bytes(chat_config.ATTACHMENT_BUCKET, key, max_bytes=stat.size, stat=stat)


async def exists(storage: StorageService, key: str, bucket: str = chat_config.ATTACHMENT_BUCKET) -> bool:
    try:
        await storage.get_stat(bucket, key)
    except ObjectNotFoundError:
        return False
    return True


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestAttachmentMediaPipeline:

    @pytest.fixture
    async def storage(self, request_container: AsyncContainer) -> StorageService:
        return await request_container.get(StorageService)

    @pytest.fixture
    def probe(self) -> FakeMediaProbe:
        return FakeMediaProbe(media_info=video_info())

    @pytest.fixture
    def transcoder(self) -> FakeMediaTranscoder:
        return FakeMediaTranscoder()

    @pytest.fixture
    async def handler(
        self,
        db_session: AsyncSession,
        attachment_repository: AttachmentRepository,
        storage: StorageService,
        redis_client: Redis,
        probe: FakeMediaProbe,
        transcoder: FakeMediaTranscoder,
    ) -> ProccessAttachmentsCommandHandler:
        return ProccessAttachmentsCommandHandler(
            attachment_repository=attachment_repository,
            storage_service=storage,
            connection_manager=ConnectionManager(
                redis=redis_client,
                presence_service=PresenceService(redis=redis_client),
                gateway_id=GATEWAY_ID,
            ),
            session=db_session,
            media_processor=AttachmentMediaProcessor(
                storage_service=storage,
                media_validator=AttachmentMediaValidator(storage_service=storage, media_probe_service=probe),
                image_renderer=AttachmentImageRenderer(),
                media_transcoder=transcoder,
            ),
        )

    async def _process(
        self,
        handler: ProccessAttachmentsCommandHandler,
        repository: AttachmentRepository,
        db_session: AsyncSession,
        s3_test_client: S3Client,
        chat: Chat,
        data: bytes,
        *,
        mime_type: str,
        attachment_type: AttachmentType = AttachmentType.IMAGE,
        filename: str = "upload.bin",
    ) -> MessageAttachment:
        slot = MessageAttachment.create(
            chat_id=chat.id,
            uploader_id=1,
            attachment_type=attachment_type,
            s3_key=f"chats/{chat.id}/{uuid4()}/{filename}",
            mime_type=mime_type,
            original_filename=filename,
            size=len(data),
        )
        await repository.create(slot)
        await db_session.commit()
        await s3_test_client.put_object(
            Bucket=chat_config.ATTACHMENT_BUCKET_PENDING, Key=slot.s3_key, Body=data
        )

        await handler.handle(
            ProccessAttachmentsCommand(chat_id=str(chat.id), user_id=1, upload_tokens=[str(slot.id)])
        )

        (stored,) = await repository.get_by_ids([slot.id])
        return stored

    async def test_photo_original_loses_exif_and_gps_and_is_turned_upright(
        self, handler, attachment_repository, db_session, storage, s3_test_client, group_chat,
    ) -> None:
        upload = make_jpeg(400, 200, orientation=6, gps=True)
        assert GPS_LATITUDE in upload

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat, upload,
            mime_type="image/jpeg", filename="IMG_0001.jpg",
        )

        assert stored.attachment_status is AttachmentStatus.SUCCESS
        original = await read_object(storage, stored.s3_key)
        assert GPS_LATITUDE not in original
        image = pyvips.Image.new_from_buffer(original, "")
        assert not [name for name in image.get_fields() if name.startswith(("exif", "xmp", "iptc"))]
        assert "orientation" not in image.get_fields()
        assert (image.width, image.height) == (200, 400)
        assert (stored.width, stored.height) == (200, 400)
        assert stored.mime_type == "image/jpeg"
        assert stored.size == len(original)
        assert not await exists(storage, stored.s3_key, chat_config.ATTACHMENT_BUCKET_PENDING)

    async def test_clean_client_jpeg_is_kept_byte_for_byte(
        self, handler, attachment_repository, db_session, storage, s3_test_client, group_chat,
    ) -> None:
        """Chatix сам жмёт фото и снимает EXIF; повторное сжатие на сервере только портит его."""
        upload = make_jpeg(1600, 1200)

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            upload, mime_type="image/jpeg",
        )

        assert stored.attachment_status is AttachmentStatus.SUCCESS
        assert await read_object(storage, stored.s3_key) == upload
        assert stored.size == len(upload)
        assert [p["size"] for p in stored.previews or []] == [320, 800, 1280]

    async def test_exif_is_cut_out_without_re_encoding(
        self, handler, attachment_repository, db_session, storage, s3_test_client, group_chat,
    ) -> None:
        plain = make_jpeg(800, 600)
        upload = make_jpeg(800, 600, orientation=1, gps=True)

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            upload, mime_type="image/jpeg",
        )

        original = await read_object(storage, stored.s3_key)
        assert GPS_LATITUDE not in original
        assert original == plain
        assert (stored.width, stored.height) == (800, 600)

    async def test_photo_gets_a_preview_ladder_and_a_thumbhash(
        self, handler, attachment_repository, db_session, storage, s3_test_client, group_chat,
    ) -> None:
        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            make_jpeg(2000, 1500), mime_type="image/jpeg",
        )

        previews = stored.previews or []
        assert [(p["size"], p["width"], p["height"]) for p in previews] == [
            (320, 320, 240), (800, 800, 600), (1280, 1280, 960),
        ]
        for preview in previews:
            assert preview["s3_key"].startswith(f"media/{group_chat.id}/{stored.id}/previews/")
            content = await read_object(storage, preview["s3_key"])
            assert len(content) == preview["file_size"]
            assert magic.from_buffer(content, mime=True) == preview["mime_type"] == "image/webp"
        assert stored.thumbhash is not None
        assert len(base64.b64decode(stored.thumbhash)) >= 5

    async def test_small_photo_gets_one_preview_at_its_own_size(
        self, handler, attachment_repository, db_session, s3_test_client, group_chat,
    ) -> None:
        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            make_jpeg(200, 150), mime_type="image/jpeg",
        )

        assert [(p["size"], p["width"], p["height"]) for p in stored.previews or []] == [(320, 200, 150)]

    async def test_png_stays_png_and_its_preview_keeps_transparency(
        self, handler, attachment_repository, db_session, storage, s3_test_client, group_chat,
    ) -> None:
        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            make_png(), mime_type="image/png",
        )

        assert magic.from_buffer(await read_object(storage, stored.s3_key), mime=True) == "image/png"
        (preview,) = stored.previews or []
        assert pyvips.Image.new_from_buffer(await read_object(storage, preview["s3_key"]), "").hasalpha()

    async def test_gif_is_promoted_byte_for_byte(
        self, handler, attachment_repository, db_session, storage, s3_test_client, group_chat,
    ) -> None:
        upload = make_gif()

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            upload, mime_type="image/gif",
        )

        assert await read_object(storage, stored.s3_key) == upload
        assert stored.previews and stored.thumbhash

    async def test_bytes_that_only_look_like_a_jpeg_are_rejected(
        self, handler, attachment_repository, db_session, storage, s3_test_client, group_chat,
    ) -> None:
        fake = make_jpeg(64, 64)[:32] + b"\x00" * 512

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            fake, mime_type="image/jpeg",
        )

        assert stored.attachment_status is AttachmentStatus.ERROR
        assert stored.previews is None
        assert not await exists(storage, stored.s3_key)

    async def test_decompression_bomb_is_rejected_before_decoding(
        self, handler, attachment_repository, db_session, storage, s3_test_client, group_chat,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(chat_config, "ATTACHMENT_IMAGE_MAX_PIXELS", 100 * 100)

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            make_jpeg(101, 100), mime_type="image/jpeg",
        )

        assert stored.attachment_status is AttachmentStatus.ERROR
        assert not await exists(storage, stored.s3_key)

    async def test_video_gets_a_poster_and_a_metadata_free_faststart_copy(
        self, handler, attachment_repository, db_session, storage, s3_test_client, group_chat,
        probe, transcoder,
    ) -> None:
        probe.media_info = video_info(width=1920, height=1080, duration=12.4, rotation=90)

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            MP4_BYTES, mime_type="video/mp4", attachment_type=AttachmentType.VIDEO,
        )

        assert stored.attachment_status is AttachmentStatus.SUCCESS
        assert (stored.width, stored.height, stored.duration_seconds) == (1080, 1920, 12)
        assert transcoder.calls == ["strip_metadata:mp4", "extract_frame:hdr=False"]
        assert await read_object(storage, stored.s3_key) == b"clean:" + MP4_BYTES
        assert stored.size == len(b"clean:" + MP4_BYTES)
        assert [p["size"] for p in stored.previews or []] == [320, 800, 1280]
        assert stored.thumbhash

    async def test_hdr_video_poster_is_tone_mapped(
        self, handler, attachment_repository, db_session, s3_test_client, group_chat, probe, transcoder,
    ) -> None:
        probe.media_info = video_info(color_transfer="arib-std-b67")

        await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            MP4_BYTES, mime_type="video/mp4", attachment_type=AttachmentType.VIDEO,
        )

        assert "extract_frame:hdr=True" in transcoder.calls

    async def test_poster_failure_still_delivers_the_video(
        self, handler, attachment_repository, db_session, s3_test_client, group_chat, transcoder,
    ) -> None:
        transcoder.frame_error = MediaTranscodeFailedError()

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            MP4_BYTES, mime_type="video/mp4", attachment_type=AttachmentType.VIDEO,
        )

        assert stored.attachment_status is AttachmentStatus.SUCCESS
        assert stored.previews is None and stored.thumbhash is None

    async def test_remux_failure_keeps_the_uploaded_bytes(
        self, handler, attachment_repository, db_session, storage, s3_test_client, group_chat, transcoder,
    ) -> None:
        transcoder.remux_error = MediaTranscodeFailedError()

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            MP4_BYTES, mime_type="video/mp4", attachment_type=AttachmentType.VIDEO,
        )

        assert stored.attachment_status is AttachmentStatus.SUCCESS
        assert await read_object(storage, stored.s3_key) == MP4_BYTES

    async def test_missing_ffmpeg_fails_the_upload_instead_of_hiding_it(
        self, handler, attachment_repository, db_session, s3_test_client, group_chat, transcoder,
    ) -> None:
        transcoder.frame_error = MediaTranscodeUnavailableError()

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            MP4_BYTES, mime_type="video/mp4", attachment_type=AttachmentType.VIDEO,
        )

        assert stored.attachment_status is AttachmentStatus.ERROR

    async def test_video_note_gets_a_poster_and_keeps_its_bytes(
        self, handler, attachment_repository, db_session, s3_test_client, group_chat, probe, transcoder,
    ) -> None:
        probe.media_info = video_info(width=480, height=480, duration=9.0)
        transcoder.frame_size = (480, 480)

        stored = await self._process(
            handler, attachment_repository, db_session, s3_test_client, group_chat,
            MP4_BYTES, mime_type="video/mp4", attachment_type=AttachmentType.VIDEO_NOTE,
        )

        assert stored.attachment_status is AttachmentStatus.SUCCESS
        assert [(p["size"], p["width"]) for p in stored.previews or []] == [(320, 320), (800, 480)]
        assert transcoder.calls == ["extract_frame:hdr=False"]

