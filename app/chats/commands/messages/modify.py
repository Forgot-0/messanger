import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.messages import MessageDTO
from app.chats.exceptions import AccessDeniedChatError, NotFoundMessageError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EditMessageCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    message_id: UUID
    new_content: str


@dataclass(frozen=True)
class EditMessageCommandHandler(BaseCommandHandler[EditMessageCommand, MessageDTO]):
    session: AsyncSession
    chat_repository: ChatRepository
    message_repository: MessageRepository
    event_bus: BaseEventBus

    async def handle(self, command: EditMessageCommand) -> MessageDTO:
        user_id = int(command.user_jwt_data.id)

        message = await self.message_repository.get_by_id(command.message_id)
        if message is None or message.chat_id != command.chat_id:
            raise NotFoundMessageError(message_id=str(command.message_id))

        if message.author_id != user_id or message.chat_id != command.chat_id:
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=user_id)

        message.update_content(command.new_content, modified_by=user_id)
        await self.event_bus.publish(message.pull_events())
        await self.session.commit()

        logger.info(
            "Message edited",
            extra={"message_id": command.message_id, "by": user_id},
        )
        return MessageDTO.model_validate(message)

