import logging
from dataclasses import dataclass
from uuid import UUID

from app.chats.exceptions import AccessDeniedChatError, InvalidUploadTokenError
from app.chats.repositories.avatar_upload import ChatAvatarUploadRepository
from app.chats.repositories.chat import ChatRepository
from app.chats.services.access import ChatAccessService
from app.chats.tasks.chat_avatar import ChatAvatarProcessTask
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData
from app.core.services.queues.service import QueueService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfirmChatAvatarUploadCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    upload_token: UUID


@dataclass(frozen=True)
class ConfirmChatAvatarUploadCommandHandler(BaseCommandHandler[ConfirmChatAvatarUploadCommand, None]):
    chat_repository: ChatRepository
    access_service: ChatAccessService
    upload_repository: ChatAvatarUploadRepository
    queue_service: QueueService

    async def handle(self, command: ConfirmChatAvatarUploadCommand) -> None:
        user_id = int(command.user_jwt_data.id)

        slot = await self.upload_repository.get(command.upload_token)
        if slot is None or slot.chat_id != command.chat_id or slot.uploader_id != user_id:
            raise InvalidUploadTokenError(token=str(command.upload_token))

        member = await self.chat_repository.get_member_chat(command.chat_id, user_id)
        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=member,
            must_permissions={"chat:update"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=user_id)

        await self.queue_service.push(
            ChatAvatarProcessTask,
            data={
                "chat_id": str(command.chat_id),
                "user_id": user_id,
                "upload_token": str(command.upload_token),
            },
        )

        logger.info(
            "Chat avatar processing queued",
            extra={"chat_id": str(command.chat_id), "user_id": user_id},
        )
