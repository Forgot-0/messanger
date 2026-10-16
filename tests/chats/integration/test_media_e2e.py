import asyncio
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.attachments.proccess import ProccessAttachmentsCommand, ProccessAttachmentsCommandHandler
from app.chats.config import chat_config
from app.chats.models.attachment import AttachmentStatus, AttachmentType, MessageAttachment
from app.chats.models.chat import Chat
from app.chats.models.message import Message, MessageType
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.services.attachment_images import AttachmentImageRenderer
from app.chats.services.attachment_media import AttachmentMediaValidator
from app.chats.services.attachment_processor import AttachmentMediaProcessor
from app.core.services.media.probe.ffprobe import FfprobeMediaProbeService
from app.core.services.media.transcode.ffmpeg import FfmpegMediaTranscoder
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

LOCATION = b"+55.7558+037.6173"


async def record_clip(path: Path) -> None:
    """Как телефон: `moov` в конце файла и геотег в метаданных."""
    process = await asyncio.create_subprocess_exec(
        FFMPEG, "-hide_banner", "-v", "error", "-y",  # type: ignore[arg-type]
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-metadata", f"location={LOCATION.decode()}/",
        str(path),
    )
    assert await process.wait() == 0


@pytest.mark.asyncio
async def test_uploaded_video_streams_with_seeking_like_telegram(
    tmp_path: Path,
    client: AsyncClient,
    create_auth_headers,
    user_jwt,
    db_session: AsyncSession,
    attachment_repository: AttachmentRepository,
    storage_service: StorageService,
    s3_test_client: S3Client,
    redis_client: Redis,
    group_chat: Chat,
) -> None:
    probe = FfprobeMediaProbeService(binary=FFPROBE)  # type: ignore[arg-type]
    transcoder = FfmpegMediaTranscoder(binary=FFMPEG, nice=0)  # type: ignore[arg-type]

    clip = tmp_path / "clip.mp4"
    await record_clip(clip)
    uploaded = clip.read_bytes()
    assert uploaded.index(b"mdat") < uploaded.index(b"moov")
    video = MessageAttachment.create(
        chat_id=group_chat.id, uploader_id=1, attachment_type=AttachmentType.VIDEO,
        s3_key=f"chats/{group_chat.id}/{uuid4()}/clip.mp4", mime_type="video/mp4",
        original_filename="clip.mp4", size=len(uploaded),
    )
    db_session.add(video)
    await db_session.commit()
    await s3_test_client.put_object(Bucket=chat_config.ATTACHMENT_BUCKET_PENDING, Key=video.s3_key, Body=uploaded)

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
    ).handle(ProccessAttachmentsCommand(chat_id=str(group_chat.id), user_id=1, upload_tokens=[str(video.id)]))

    (stored,) = await attachment_repository.get_by_ids([video.id])
    await db_session.refresh(stored)
    assert stored.attachment_status is AttachmentStatus.SUCCESS
    assert (stored.width, stored.height, stored.duration_seconds) == (1280, 720, 6)
    assert [p["size"] for p in stored.previews or []] == [320, 800, 1280]

    message = Message.create(
        sender_id=1, chat_id=group_chat.id, seq=1, content=None, message_type=MessageType.IMAGE, attachments=[stored],
    )
    db_session.add(message)
    await db_session.commit()

    download = await client.get(
        api_path(f"chats/{group_chat.id}/messages/{message.id}/attachments/{stored.id}/download-url/"),
        headers=create_auth_headers(user_jwt),
    )
    url = download.json()["url"]

    async with httpx.AsyncClient() as player:
        head = await player.get(url, headers={"Range": "bytes=0-65535"})
        tail_start = stored.size - 65_536
        tail = await player.get(url, headers={"Range": f"bytes={tail_start}-{stored.size - 1}"})

    # Плеер сразу находит индекс в начале и прыгает в любой кусок — без скачивания файла целиком.
    assert head.status_code == tail.status_code == 206
    assert b"moov" in head.content
    assert head.content.index(b"moov") < head.content.index(b"mdat")
    assert LOCATION not in head.content
    assert len(tail.content) == 65_536
