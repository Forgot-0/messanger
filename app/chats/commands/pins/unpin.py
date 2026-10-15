import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import NotFoundChatError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.pinned_message import ChatPinnedMessageRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnpinMessagesCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    message_id: UUID | None = None


@dataclass(frozen=True)
class UnpinMessagesCommandHandler(BaseCommandHandler[UnpinMessagesCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    pin_repository: ChatPinnedMessageRepository
    chat_access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: UnpinMessagesCommand) -> None:
        user_id = int(command.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(command.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        member = await self.chat_repository.get_member_chat(command.chat_id, user_id)
        await self.chat_access_service.ensure_can_pin(command.user_jwt_data, member, command.chat_id)

        unpin_all = command.message_id is None
        if command.message_id is None:
            unpinned = await self.pin_repository.delete_all(command.chat_id)
        else:
            unpinned = await self.pin_repository.delete_many(command.chat_id, [command.message_id])

        if not unpinned:
            return

        chat.unpin_messages(unpinned, unpinned_by=user_id, unpin_all=unpin_all)
        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()

        logger.info(
            "Messages unpinned",
            extra={
                "chat_id": command.chat_id,
                "count": len(unpinned),
                "all": unpin_all,
                "by": user_id,
            },
        )
