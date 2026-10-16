from datetime import datetime
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.chats.config import chat_config
from app.chats.dtos.attachments import AttachmentDTO, AttachmentPreviewDTO
from app.chats.dtos.messages import MessageDTO
from app.chats.keys import AttachmentKeys
from app.chats.models.attachment import AttachmentStatus, AttachmentType
from app.chats.models.message import MessageType
from app.chats.services.messages import MessageService
from tests.support.http import assert_presigned_url


def attachment_dto(s3_key: str, *previews: str) -> AttachmentDTO:
    return AttachmentDTO(
        id=uuid4(), message_id=uuid4(), chat_id=uuid4(), uploader_id=1,
        attachment_type=AttachmentType.VIDEO, attachment_status=AttachmentStatus.SUCCESS,
        s3_key=s3_key, mime_type="video/mp4", original_filename="clip.mp4", size=1,
        width=1280, height=720, duration_seconds=3, created_at=datetime.now(),
        previews=[
            AttachmentPreviewDTO(size=320, width=320, height=180, mime_type="image/webp", file_size=1, s3_key=key)
            for key in previews
        ],
    )


def message_dto(*attachments: AttachmentDTO, reply_to: MessageDTO | None = None) -> MessageDTO:
    return MessageDTO(
        id=uuid4(), chat_id=uuid4(), seq=1, author_id=1, type=MessageType.IMAGE, content=None,
        reply_to_id=reply_to.id if reply_to else None, forwarded_from_chat_id=None,
        forwarded_from_message_id=None, forwarded_from_author_id=None, is_edited=False,
        created_at=datetime.now(), attachments=list(attachments), reply_to=reply_to,
    )


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMessageAttachmentUrls:

    async def test_originals_previews_and_quoted_attachments_get_links(
        self, message_service: MessageService,
    ) -> None:
        quoted = attachment_dto("chats/q/1/photo.jpg", "media/q/1/previews/320.webp")
        video = attachment_dto("chats/c/2/clip.mp4", "media/c/2/previews/320.webp")

        await message_service.attach_download_urls(message_dto(video, reply_to=message_dto(quoted)))

        for item in (video, quoted):
            assert_presigned_url(item.url or "", bucket=chat_config.ATTACHMENT_BUCKET, file_key=item.s3_key)
            assert_presigned_url(item.previews[0].url or "", bucket=chat_config.ATTACHMENT_BUCKET, file_key="320.webp")
            assert item.url_expires_in == item.previews[0].url_expires_in == chat_config.DOWNLOAD_URL_TTL

    async def test_links_are_cached_per_key_and_reused(
        self, message_service: MessageService, redis_client: Redis,
    ) -> None:
        key = f"chats/c/{uuid4()}/photo.jpg"
        await redis_client.set(AttachmentKeys.download_url(key), "https://cached.test/link", ex=60)
        fresh_key = f"chats/c/{uuid4()}/other.jpg"

        urls = await message_service.presigned_attachment_urls([key, fresh_key, key])

        assert urls[key] == "https://cached.test/link"
        assert await redis_client.get(AttachmentKeys.download_url(fresh_key)) == urls[fresh_key]
        assert 0 < await redis_client.ttl(AttachmentKeys.download_url(fresh_key)) <= chat_config.DOWNLOAD_URL_TTL - 30

    async def test_legacy_absolute_keys_are_passed_through(self, message_service: MessageService) -> None:
        urls = await message_service.presigned_attachment_urls(["https://cdn.test/a.jpg"])

        assert urls == {"https://cdn.test/a.jpg": "https://cdn.test/a.jpg"}
