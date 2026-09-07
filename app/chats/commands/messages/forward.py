import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.messages import MessageDTO
from app.chats.exceptions import (
    AccessDeniedChatError,
    NotChatMemberError,
    NotFoundChatError,
    NotFoundMessageError,
)
from app.chats.models.attachment import AttachmentStatus
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


@dataclass(frozen=True)
class ForwardMessageCommand(BaseCommand):
    user_jwt_data: UserJWTData
    source_chat_id: UUID
    source_message_id: UUID
    target_chat_id: UUID
    comment: str | None = None


@dataclass(frozen=True)
class ForwardMessageCommandHandler(BaseCommandHandler[ForwardMessageCommand, MessageDTO]):
    session: AsyncSession
    chat_repository: ChatRepository
    message_repository: MessageRepository
    attachment_repository: AttachmentRepository
    chat_access_service: ChatAccessService
    message_service: MessageService
    event_bus: BaseEventBus

    async def handle(self, command: ForwardMessageCommand) -> MessageDTO:
        user_id = int(command.user_jwt_data.id)

        source_member = await self.chat_repository.get_member_chat(
            command.source_chat_id, user_id
        )
        if source_member is None:
            raise NotChatMemberError(chat_id=str(command.source_chat_id), user_id=user_id)

        source_msg = await self.message_repository.get_by_id(command.source_message_id, with_attachment=True)
        if source_msg is None or source_msg.chat_id != command.source_chat_id or source_msg.is_deleted:
            raise NotFoundMessageError(message_id=str(command.source_message_id))

        if not await self.chat_access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=source_member,
            must_permissions={"message:read"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.source_chat_id), requester_id=user_id)

        target_chat, target_member = await self.chat_repository.get_chat_and_member(
            chat_id=command.target_chat_id, member_id=user_id
        )

        if not await self.chat_access_service.can_send_message(
            user_jwt_data=command.user_jwt_data,
            chat=target_chat,
            member=target_member,
        ):
            raise AccessDeniedChatError(chat_id=str(command.target_chat_id), requester_id=user_id)

        await self.message_service.is_slow(
            chat=target_chat,
            user_id=user_id,
            member=target_member,
        )

        forward_attachments = []
        for attachment in source_msg.attachments:
            if attachment.attachment_status != AttachmentStatus.SUCCESS:
                continue

            atch = attachment.create_for_forward(chat_id=target_chat.id)
            forward_attachments.append(atch)

        message_date = now_utc()
        next_seq = await self.chat_repository.allocate_message_seq(
            chat_id=command.target_chat_id,
            message_date=message_date,
        )
        if next_seq is None:
            raise NotFoundChatError(chat_id=str(command.target_chat_id))

        forwarded_msg = Message.create(
            sender_id=user_id,
            chat_id=command.target_chat_id,
            seq=next_seq,
            content=command.comment or source_msg.content,
            message_type=MessageType.FORWARD,
            forwarded_from_chat_id=(
                source_msg.chat_id
                if source_msg.forwarded_from_chat_id is None
                else source_msg.forwarded_from_chat_id
            ),
            forwarded_from_message_id=(
                source_msg.id
                if source_msg.forwarded_from_message_id is None
                else source_msg.forwarded_from_message_id
            ),
            forwarded_from_author_id=(
                source_msg.author_id
                if source_msg.forwarded_from_author_id is None
                else source_msg.forwarded_from_author_id
            ),
            attachments=forward_attachments
        )
        await self.message_repository.create(forwarded_msg)
        await self.event_bus.publish(forwarded_msg.pull_events())
        await self.session.commit()

        logger.info(
            "Message forwarded",
            extra={
                "source_chat_id": command.source_chat_id,
                "source_message_id": command.source_message_id,
                "target_chat_id": command.target_chat_id,
                "new_message_id": forwarded_msg.id,
                "by": user_id,
            },
        )
        dto = MessageDTO.model_validate(forwarded_msg)
        return await self.message_service.attach_download_urls(dto)
