import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.messages import MessageDTO
from app.chats.dtos.pins import PinnedMessageDTO
from app.chats.exceptions import NotFoundChatError, NotFoundMessageError
from app.chats.models.message import Message, SystemMessageAction
from app.chats.models.pinned_message import ChatPinnedMessage
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.repositories.pinned_message import ChatPinnedMessageRepository
from app.chats.services.access import ChatAccessService
from app.chats.services.messages import MessageService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PinMessageCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    message_id: UUID


@dataclass(frozen=True)
class PinMessageCommandHandler(BaseCommandHandler[PinMessageCommand, PinnedMessageDTO]):
    session: AsyncSession
    chat_repository: ChatRepository
    message_repository: MessageRepository
    pin_repository: ChatPinnedMessageRepository
    chat_access_service: ChatAccessService
    message_service: MessageService
    event_bus: BaseEventBus

    async def handle(self, command: PinMessageCommand) -> PinnedMessageDTO:
        user_id = int(command.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(command.chat_id, with_for_update=True)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        member = await self.chat_repository.get_member_chat(command.chat_id, user_id)
        await self.chat_access_service.ensure_can_pin(command.user_jwt_data, member, command.chat_id)

        message = await self.message_repository.get_by_id(command.message_id, with_attachment=True)
        if message is None or message.chat_id != command.chat_id:
            raise NotFoundMessageError(message_id=str(command.message_id))

        existing = await self.pin_repository.get(command.chat_id, command.message_id)
        if existing is not None:
            return await self._to_dto(existing, message)

        pin = chat.pin_message(
            message,
            pinned_by=user_id,
            pinned_count=await self.pin_repository.count(command.chat_id),
        )
        await self.pin_repository.create(pin)

        seq = await self.chat_repository.allocate_message_seq(
            chat_id=command.chat_id, message_date=now_utc()
        )
        if seq is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        notice = Message.create_system(
            actor_id=user_id,
            chat_id=command.chat_id,
            seq=seq,
            action=SystemMessageAction.MESSAGE_PINNED,
            reply_to_id=message.id,
        )
        await self.message_repository.create(notice)

        await self.event_bus.publish([*chat.pull_events(), *notice.pull_events()])
        await self.session.commit()

        logger.info(
            "Message pinned",
            extra={
                "chat_id": command.chat_id,
                "message_id": command.message_id,
                "notice_id": notice.id,
                "by": user_id,
            },
        )
        return await self._to_dto(pin, message)

    async def _to_dto(self, pin: ChatPinnedMessage, message: Message) -> PinnedMessageDTO:
        return PinnedMessageDTO(
            message=await self.message_service.attach_download_urls(MessageDTO.model_validate(message)),
            pinned_by=pin.pinned_by,
            pinned_at=pin.pinned_at,
        )
