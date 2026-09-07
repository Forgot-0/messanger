import logging
from dataclasses import dataclass
from uuid import UUID

from app.chats.tasks.success_attachment import AttachmentProccessTask
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData
from app.core.services.queues.service import QueueService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SuccessUploadAttachmentsCommand(BaseCommand):
    chat_id: UUID
    upload_tokens: list[str]
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class SuccessUploadAttachmentsCommandHandler(BaseCommandHandler[SuccessUploadAttachmentsCommand, None]):
    queue_service: QueueService

    async def handle(self, command: SuccessUploadAttachmentsCommand) -> None:
        await self.queue_service.push(
            AttachmentProccessTask, data={
                "user_id": int(command.user_jwt_data.id),
                "chat_id": str(command.chat_id),
                "upload_tokens": command.upload_tokens
            }
        )

        logger.info(
            "Proccess attachment in task", extra={
                "user_id": int(command.user_jwt_data.id),
                "chat_id": command.chat_id,
                "upload_tokens": command.upload_tokens
            }
        )
