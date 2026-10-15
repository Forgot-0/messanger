import asyncio
import re
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from dishka import AsyncContainer
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.attachments.proccess import ProccessAttachmentsCommand, ProccessAttachmentsCommandHandler
from app.chats.commands.attachments.transcode import TranscodeAttachmentCommand, TranscodeAttachmentCommandHandler
from app.chats.config import chat_config
from app.chats.models.attachment import AttachmentStatus, AttachmentType, HlsStatus, MessageAttachment
from app.chats.models.chat import Chat
from app.chats.models.message import Message, MessageType
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.services.attachment_images import AttachmentImageRenderer
from app.chats.services.attachment_media import AttachmentMediaValidator
from app.chats.services.attachment_processor import AttachmentMediaProcessor
from app.core.services.media.probe.ffprobe import FfprobeMediaProbeService
from app.core.services.media.transcode.ffmpeg import FfmpegMediaTranscoder
from app.core.services.queues.service import QueueService
from app.core.services.storage.aioboto.client import S3Client
from app.core.services.storage.service import StorageService
from app.core.websocket.manager import ConnectionManager
from app.core.websocket.presence import PresenceService
from tests.chats.integration.conftest import GATEWAY_ID
from tests.support.http import api_path
from tests.support.media import media_tool

FFMPEG = media_tool("ffmpeg")
FFPROBE = media_tool("ffprobe")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.chats,
    pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="ffmpeg/ffprobe are not installed"),
]

BYTERANGE = re.compile(r"(?:#EXT-X-BYTERANGE:|BYTERANGE=\")(\d+)@(\d+)")


async def record_clip(path: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        FFMPEG, "-hide_banner", "-v", "error", "-y",  # type: ignore[arg-type]
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-metadata", "location=+55.7558+037.6173/",
        str(path),
    )
    assert await process.wait() == 0


@pytest.mark.asyncio
async def test_uploaded_video_becomes_a_seekable_hls_stream(
    tmp_path: Path,
    client: AsyncClient,
    create_auth_headers,
    user_jwt,
    request_container: AsyncContainer,
    db_session: AsyncSession,
    attachment_repository: AttachmentRepository,
    storage_service: StorageService,
    s3_test_client: S3Client,
    redis_client: Redis,
    group_chat: Chat,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_config, "VIDEO_HLS_PRESET", "ultrafast")
    probe = FfprobeMediaProbeService(binary=FFPROBE)  # type: ignore[arg-type]
    transcoder = FfmpegMediaTranscoder(binary=FFMPEG, probe_binary=FFPROBE, nice=0)  # type: ignore[arg-type]

    clip = tmp_path / "clip.mp4"
    await record_clip(clip)
    video = MessageAttachment.create(
        chat_id=group_chat.id, uploader_id=1, attachment_type=AttachmentType.VIDEO,
        s3_key=f"chats/{group_chat.id}/{uuid4()}/clip.mp4", mime_type="video/mp4",
        original_filename="clip.mp4", size=clip.stat().st_size,
    )
    db_session.add(video)
    await db_session.commit()
    await s3_test_client.put_object(
        Bucket=chat_config.ATTACHMENT_BUCKET_PENDING, Key=video.s3_key, Body=clip.read_bytes()
    )

    await ProccessAttachmentsCommandHandler(
        attachment_repository=attachment_repository,
        storage_service=storage_service,
        connection_manager=ConnectionManager(
            redis=redis_client, presence_service=PresenceService(redis=redis_client), gateway_id=GATEWAY_ID,
        ),
        session=db_session,
        media_processor=AttachmentMediaProcessor(
            storage_service=storage_service,
            media_validator=AttachmentMediaValidator(storage_service=storage_service, media_probe_service=probe),
            image_renderer=AttachmentImageRenderer(),
            media_transcoder=transcoder,
        ),
        queue_service=await request_container.get(QueueService),
    ).handle(ProccessAttachmentsCommand(chat_id=str(group_chat.id), user_id=1, upload_tokens=[str(video.id)]))

    await TranscodeAttachmentCommandHandler(
        session=db_session,
        attachment_repository=attachment_repository,
        storage_service=storage_service,
        media_probe_service=probe,
        media_transcoder=transcoder,
        redis=redis_client,
    ).handle(TranscodeAttachmentCommand(attachment_id=str(video.id)))

    (stored,) = await attachment_repository.get_by_ids([video.id])
    await db_session.refresh(stored)
    assert stored.attachment_status is AttachmentStatus.SUCCESS
    assert (stored.width, stored.height, stored.duration_seconds) == (1280, 720, 6)
    assert [p["size"] for p in stored.previews or []] == [320, 800, 1280]
    assert stored.hls_status is HlsStatus.READY

    message = Message.create(
        sender_id=1, chat_id=group_chat.id, seq=1, content=None, message_type=MessageType.IMAGE, attachments=[stored],
    )
    db_session.add(message)
    await db_session.commit()

    headers = create_auth_headers(user_jwt)
    download = await client.get(
        api_path(f"chats/{group_chat.id}/messages/{message.id}/attachments/{stored.id}/download-url/"),
        headers=headers,
    )
    async with httpx.AsyncClient() as storage_http:
        original = (await storage_http.get(download.json()["url"])).content
        assert b"+55.7558+037.6173" not in original

        master_url = download.json()["hls_url"]
        master = (await client.get(master_url)).text
        variants = [line for line in master.splitlines() if line.endswith(".m3u8")]
        assert variants == ["v0.m3u8", "v1.m3u8"]

        playlist = (await client.get(master_url.rsplit("/", 1)[0] + "/v1.m3u8")).text
        (media_url,) = {line for line in playlist.splitlines() if line.startswith("http")}
        ranges = [(int(length), int(offset)) for length, offset in BYTERANGE.findall(playlist)]
        assert len(ranges) >= 3

        # Перемотка: init-секция и сразу последний сегмент — без скачивания середины.
        chunks = []
        for length, offset in (ranges[0], ranges[-1]):
            response = await storage_http.get(
                media_url, headers={"Range": f"bytes={offset}-{offset + length - 1}"}
            )
            assert response.status_code == 206
            chunks.append(response.content)

    fragment = tmp_path / "seek.mp4"
    fragment.write_bytes(b"".join(chunks))
    info = await probe.probe(fragment)
    assert info.video_streams[0].codec_name == "h264"
    assert info.video_streams[0].display_size == (1280, 720)
