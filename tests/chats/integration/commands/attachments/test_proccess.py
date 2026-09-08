import io
from uuid import UUID, uuid4

import pytest
from dishka import AsyncContainer
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.attachments.proccess import (
    ProccessAttachmentsCommand,
    ProccessAttachmentsCommandHandler,
)
from app.chats.config import chat_config
from app.chats.models.attachment import AttachmentStatus, AttachmentType, MessageAttachment
from app.chats.models.chat import Chat
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.services.attachment_media import AttachmentMediaValidator
from app.core.services.storage.exceptions import ObjectNotFoundError
from app.core.services.storage.service import StorageService
from app.core.websocket.manager import ConnectionManager
from app.core.websocket.presence import PresenceService
from tests.chats.integration.conftest import GATEWAY_ID

JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
PDF_HEADER = b"%PDF-1.4\n"
TEXT_BYTES = b"totally not a jpeg\n" * 4


def put_object(client: Minio, bucket: str, key: str, data: bytes) -> None:
    client.put_object(bucket, key, io.BytesIO(data), length=len(data))


async def object_exists(storage: StorageService, bucket: str, key: str) -> bool:
    try:
        await storage.get_stat(bucket_name=bucket, file_key=key)
    except ObjectNotFoundError:
        return False
    return True


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestProccessAttachments:

    @pytest.fixture
    async def storage(self, request_container: AsyncContainer) -> StorageService:
        return await request_container.get(StorageService)

    @pytest.fixture
    async def attachment_repository(
        self, request_container: AsyncContainer
    ) -> AttachmentRepository:
        return await request_container.get(AttachmentRepository)

    @pytest.fixture
    async def handler(
        self,
        request_container: AsyncContainer,
        db_session: AsyncSession,
        attachment_repository: AttachmentRepository,
        storage: StorageService,
        redis_client: Redis,
    ) -> ProccessAttachmentsCommandHandler:
        validator = await request_container.get(AttachmentMediaValidator)
        return ProccessAttachmentsCommandHandler(
            attachment_repository=attachment_repository,
            storage_service=storage,
            connection_manager=ConnectionManager(
                redis=redis_client,
                presence_service=PresenceService(redis=redis_client),
                gateway_id=GATEWAY_ID,
            ),
            session=db_session,
            media_validator=validator,
        )

    async def _slot(
        self,
        repository: AttachmentRepository,
        db_session: AsyncSession,
        minio_client: Minio,
        chat: Chat,
        *,
        uploader_id: int = 1,
        mime_type: str = "image/jpeg",
        declared_size: int | None = None,
        real_bytes: bytes = JPEG_HEADER,
        upload: bool = True,
    ) -> MessageAttachment:
        attachment = MessageAttachment.create(
            chat_id=chat.id,
            uploader_id=uploader_id,
            attachment_type=AttachmentType.IMAGE,
            s3_key=f"chats/{chat.id}/{uuid4()}/photo.jpg",
            mime_type=mime_type,
            original_filename="photo.jpg",
            size=declared_size if declared_size is not None else len(real_bytes),
        )
        await repository.create(attachment)
        await db_session.commit()

        if upload:
            put_object(
                minio_client,
                chat_config.ATTACHMENT_BUCKET_PENDING,
                attachment.s3_key,
                real_bytes,
            )
        return attachment

    async def _run(
        self,
        handler: ProccessAttachmentsCommandHandler,
        chat: Chat,
        tokens: list[UUID],
        user_id: int = 1,
    ) -> None:
        await handler.handle(
            ProccessAttachmentsCommand(
                chat_id=str(chat.id),
                user_id=user_id,
                upload_tokens=[str(t) for t in tokens],
            )
        )

    async def _status(
        self, repository: AttachmentRepository, attachment_id: UUID
    ) -> AttachmentStatus:
        (stored,) = await repository.get_by_ids([attachment_id])
        return stored.attachment_status

    async def test_matching_upload_is_promoted_to_the_main_bucket(
        self,
        handler: ProccessAttachmentsCommandHandler,
        attachment_repository: AttachmentRepository,
        db_session: AsyncSession,
        storage: StorageService,
        minio_client: Minio,
        group_chat: Chat,
    ) -> None:
        slot = await self._slot(attachment_repository, db_session, minio_client, group_chat)

        await self._run(handler, group_chat, [slot.id])

        assert await self._status(attachment_repository, slot.id) is AttachmentStatus.SUCCESS
        assert await object_exists(storage, chat_config.ATTACHMENT_BUCKET, slot.s3_key)
        assert not await object_exists(
            storage, chat_config.ATTACHMENT_BUCKET_PENDING, slot.s3_key
        )

    async def test_promoted_object_keeps_its_bytes(
        self,
        handler: ProccessAttachmentsCommandHandler,
        attachment_repository: AttachmentRepository,
        db_session: AsyncSession,
        storage: StorageService,
        minio_client: Minio,
        group_chat: Chat,
    ) -> None:
        slot = await self._slot(attachment_repository, db_session, minio_client, group_chat)

        await self._run(handler, group_chat, [slot.id])

        moved = await storage.download_range(
            bucket_name=chat_config.ATTACHMENT_BUCKET,
            file_key=slot.s3_key,
            offset=0,
            length=len(JPEG_HEADER),
        )
        assert moved == JPEG_HEADER

    @pytest.mark.parametrize(
        "real_bytes,label", [(PDF_HEADER, "pdf"), (TEXT_BYTES, "текст")]
    )
    async def test_declared_jpeg_with_foreign_bytes_is_rejected(
        self,
        handler: ProccessAttachmentsCommandHandler,
        attachment_repository: AttachmentRepository,
        db_session: AsyncSession,
        storage: StorageService,
        minio_client: Minio,
        group_chat: Chat,
        real_bytes: bytes,
        label: str,
    ) -> None:
        slot = await self._slot(
            attachment_repository, db_session, minio_client, group_chat, real_bytes=real_bytes
        )

        await self._run(handler, group_chat, [slot.id])

        assert await self._status(attachment_repository, slot.id) is AttachmentStatus.ERROR
        assert not await object_exists(storage, chat_config.ATTACHMENT_BUCKET, slot.s3_key)
        assert await object_exists(
            storage, chat_config.ATTACHMENT_BUCKET_PENDING, slot.s3_key
        )

    async def test_object_larger_than_declared_is_rejected(
        self,
        handler: ProccessAttachmentsCommandHandler,
        attachment_repository: AttachmentRepository,
        db_session: AsyncSession,
        storage: StorageService,
        minio_client: Minio,
        group_chat: Chat,
    ) -> None:
        slot = await self._slot(
            attachment_repository,
            db_session,
            minio_client,
            group_chat,
            declared_size=4,
            real_bytes=JPEG_HEADER,
        )

        await self._run(handler, group_chat, [slot.id])

        assert await self._status(attachment_repository, slot.id) is AttachmentStatus.ERROR
        assert not await object_exists(storage, chat_config.ATTACHMENT_BUCKET, slot.s3_key)

    async def test_empty_object_is_rejected(
        self,
        handler: ProccessAttachmentsCommandHandler,
        attachment_repository: AttachmentRepository,
        db_session: AsyncSession,
        minio_client: Minio,
        group_chat: Chat,
    ) -> None:
        slot = await self._slot(
            attachment_repository, db_session, minio_client, group_chat, real_bytes=b""
        )

        await self._run(handler, group_chat, [slot.id])

        assert await self._status(attachment_repository, slot.id) is AttachmentStatus.ERROR

    async def test_slot_without_an_uploaded_object_is_rejected(
        self,
        handler: ProccessAttachmentsCommandHandler,
        attachment_repository: AttachmentRepository,
        db_session: AsyncSession,
        minio_client: Minio,
        group_chat: Chat,
    ) -> None:
        slot = await self._slot(
            attachment_repository, db_session, minio_client, group_chat, upload=False
        )

        await self._run(handler, group_chat, [slot.id])

        assert await self._status(attachment_repository, slot.id) is AttachmentStatus.ERROR

    async def test_foreign_slot_is_not_processed(
        self,
        handler: ProccessAttachmentsCommandHandler,
        attachment_repository: AttachmentRepository,
        db_session: AsyncSession,
        storage: StorageService,
        minio_client: Minio,
        group_chat: Chat,
    ) -> None:
        slot = await self._slot(
            attachment_repository, db_session, minio_client, group_chat, uploader_id=2
        )

        await self._run(handler, group_chat, [slot.id], user_id=1)

        assert await self._status(attachment_repository, slot.id) is AttachmentStatus.ERROR
        assert not await object_exists(storage, chat_config.ATTACHMENT_BUCKET, slot.s3_key)

    async def test_one_bad_upload_does_not_stop_the_others(
        self,
        handler: ProccessAttachmentsCommandHandler,
        attachment_repository: AttachmentRepository,
        db_session: AsyncSession,
        minio_client: Minio,
        group_chat: Chat,
    ) -> None:
        good_one = await self._slot(attachment_repository, db_session, minio_client, group_chat)
        bad = await self._slot(
            attachment_repository, db_session, minio_client, group_chat, real_bytes=PDF_HEADER
        )
        good_two = await self._slot(attachment_repository, db_session, minio_client, group_chat)

        await self._run(handler, group_chat, [good_one.id, bad.id, good_two.id])

        assert await self._status(attachment_repository, good_one.id) is AttachmentStatus.SUCCESS
        assert await self._status(attachment_repository, bad.id) is AttachmentStatus.ERROR
        assert await self._status(attachment_repository, good_two.id) is AttachmentStatus.SUCCESS

    async def test_unknown_token_is_ignored_without_failing(
        self,
        handler: ProccessAttachmentsCommandHandler,
        attachment_repository: AttachmentRepository,
        db_session: AsyncSession,
        minio_client: Minio,
        group_chat: Chat,
    ) -> None:
        slot = await self._slot(attachment_repository, db_session, minio_client, group_chat)

        await self._run(handler, group_chat, [slot.id, uuid4()])

        assert await self._status(attachment_repository, slot.id) is AttachmentStatus.SUCCESS
