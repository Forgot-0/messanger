import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.chats.config import chat_config
from app.chats.dtos.avatars import ChatAvatarUploadSlotDTO
from app.chats.exceptions import (
    AccessDeniedChatError,
    ChatAvatarValidationError,
    NotFoundChatError,
)
from app.chats.models.chat import ChatType
from app.chats.repositories.avatar_upload import ChatAvatarUploadRepository, ChatAvatarUploadSlot
from app.chats.repositories.chat import ChatRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData
from app.core.services.storage.service import StorageService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestChatAvatarUploadCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    mime_type: str
    file_size: int


@dataclass(frozen=True)
class RequestChatAvatarUploadCommandHandler(
    BaseCommandHandler[RequestChatAvatarUploadCommand, ChatAvatarUploadSlotDTO]
):
    chat_repository: ChatRepository
    access_service: ChatAccessService
    upload_repository: ChatAvatarUploadRepository
    storage_service: StorageService

    async def handle(self, command: RequestChatAvatarUploadCommand) -> ChatAvatarUploadSlotDTO:
        user_id = int(command.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(command.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        member = await self.chat_repository.get_member_chat(command.chat_id, user_id)
        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=member,
            must_permissions={"chat:update"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=user_id)

        if chat.type == ChatType.DIRECT:
            raise ChatAvatarValidationError(reason="direct_chat")

        if command.mime_type not in chat_config.CHAT_AVATAR_ALLOWED_MIMES:
            raise ChatAvatarValidationError(reason="mime_type", mime_type=command.mime_type)

        if command.file_size <= 0 or command.file_size > chat_config.CHAT_AVATAR_MAX_SIZE:
            raise ChatAvatarValidationError(reason="size", file_size=command.file_size)

        upload_token = uuid4()
        s3_key = f"{chat.id}/{upload_token}"

        upload_url = await self.storage_service.upload_put_url(
            bucket_name=chat_config.CHAT_AVATAR_BUCKET_PENDING,
            file_key=s3_key,
            expires=chat_config.CHAT_AVATAR_UPLOAD_TTL,
        )
        await self.upload_repository.save(
            ChatAvatarUploadSlot(
                upload_token=upload_token,
                chat_id=chat.id,
                uploader_id=user_id,
                s3_key=s3_key,
                mime_type=command.mime_type,
                file_size=command.file_size,
            )
        )

        logger.info(
            "Chat avatar upload slot created",
            extra={"chat_id": str(chat.id), "user_id": user_id, "upload_token": str(upload_token)},
        )
        return ChatAvatarUploadSlotDTO(
            upload_token=upload_token,
            upload_url=upload_url,
            expires_in=chat_config.CHAT_AVATAR_UPLOAD_TTL,
        )
