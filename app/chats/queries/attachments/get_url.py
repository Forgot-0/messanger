from dataclasses import dataclass
from uuid import UUID

from app.chats.config import chat_config
from app.chats.dtos.attachments import AttachmentDownloadUrlDTO
from app.chats.exceptions import (
    AttachmentNotFoundError,
    NotChatMemberError,
)
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.repositories.chat import ChatRepository
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.core.services.storage.service import StorageService


@dataclass(frozen=True)
class GetAttachmentDownloadUrlQuery(BaseQuery):
    user_jwt_data: UserJWTData
    chat_id: UUID
    message_id: UUID
    attachment_id: UUID


@dataclass(frozen=True)
class GetAttachmentDownloadUrlQueryHandler(
    BaseQueryHandler[GetAttachmentDownloadUrlQuery, AttachmentDownloadUrlDTO]
):
    chat_repository: ChatRepository
    attachment_repository: AttachmentRepository
    storage_service: StorageService

    async def handle(self, query: GetAttachmentDownloadUrlQuery) -> AttachmentDownloadUrlDTO:
        user_id = int(query.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(query.chat_id, user_id)
        if not member:
            raise NotChatMemberError(chat_id=str(query.chat_id), user_id=user_id)

        attachment = await self.attachment_repository.get_by_id(query.attachment_id)
        if (
            attachment is None
            or attachment.message_id != query.message_id
            or attachment.chat_id != query.chat_id
        ):
            raise AttachmentNotFoundError(attachment_id=str(query.attachment_id))

        return await self.attachment_repository.cache(
            AttachmentDownloadUrlDTO,  self._handle, chat_config.DOWNLOAD_URL_TTL,
            attachment_id=attachment.id, s3_key=attachment.s3_key
        )

    async def _handle(self, attachment_id: UUID, s3_key: str) -> AttachmentDownloadUrlDTO:
        url = await self.storage_service.generate_presigned_url(
            bucket_name=chat_config.ATTACHMENT_BUCKET,
            file_key=s3_key,
            expires=chat_config.DOWNLOAD_URL_TTL,
        )

        return AttachmentDownloadUrlDTO(
            attachment_id=attachment_id,
            url=url,
            expires_in=chat_config.DOWNLOAD_URL_TTL,
        )
