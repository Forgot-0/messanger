import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.messages import MessageDTO
from app.chats.exceptions import (
    AccessDeniedChatError,
    AttachmentNotFoundError,
    NotFoundChatError,
    NotFoundMessageError,
)
from app.chats.models.message import Message, MessageType
from app.chats.repositories.attachment import AttachmentRepository
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.services.access import ChatAccessService
from app.chats.services.messages import MessageService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SendMessageCommand(BaseCommand):
    chat_id: UUID
    content: str | None
    reply_to_id: UUID | None = None
    message_type: MessageType = MessageType.TEXT
    upload_tokens: list[UUID] = field(default_factory=list)

    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class SendMessageCommandHandler(BaseCommandHandler[SendMessageCommand, MessageDTO]):
    session: AsyncSession
    chat_repository: ChatRepository
    access_service: ChatAccessService
    message_repository: MessageRepository
    attachment_repository: AttachmentRepository
    message_service: MessageService
    event_bus: BaseEventBus

    async def handle(self, command: SendMessageCommand) -> MessageDTO:
        user_id = int(command.user_jwt_data.id)

        chat, member = await self.chat_repository.get_chat_and_member(
            chat_id=command.chat_id, member_id=user_id
        )


        if not await self.access_service.can_send_message(
            user_jwt_data=command.user_jwt_data,
            chat=chat,
            member=member,
        ):
            raise AccessDeniedChatError(
                chat_id=str(command.chat_id), requester_id=user_id
            )

        await self.message_service.is_slow(chat=chat, user_id=user_id, member=member)

        claimed = []
        if command.upload_tokens:
            claimed = await self.attachment_repository.get_by_ids(command.upload_tokens)

        if claimed and len(command.upload_tokens) != len(claimed):
            raise AttachmentNotFoundError(attachment_id="")

        if command.reply_to_id is not None:
            reply_msg = await self.message_repository.get_by_id(command.reply_to_id)
            if reply_msg is None:
                raise NotFoundMessageError(message_id=str(command.reply_to_id))

        message_date = now_utc()
        next_seq = await self.chat_repository.allocate_message_seq(
            chat_id=command.chat_id,
            message_date=message_date,
        )
        if next_seq is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        msg = Message.create(
            sender_id=user_id,
            chat_id=command.chat_id,
            seq=next_seq,
            content=command.content,
            reply_to_id=command.reply_to_id,
            message_type=command.message_type,
            attachments=claimed,
        )

        await self.message_repository.create(msg)
        await self.event_bus.publish(msg.pull_events())
        await self.session.commit()

        logger.info(
            "Message sent",
            extra={
                "chat_id": command.chat_id,
                "message_id": msg.id,
                "author": user_id,
                "attachments": len(claimed),
                "fanout_strategy": chat.fanout_strategy.value,
            },
        )
        dto = MessageDTO.model_validate(msg)
        return await self.message_service.attach_download_urls(dto)
