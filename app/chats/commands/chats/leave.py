import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import NotChatMemberError, NotFoundChatError
from app.chats.repositories.chat import ChatRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LeaveChatCommand(BaseCommand):
    chat_id: UUID
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class LeaveChatCommandHandler(BaseCommandHandler[LeaveChatCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: LeaveChatCommand) -> None:
        chat = await self.chat_repository.get_by_id(command.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        user_id = int(command.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(command.chat_id, member_id=user_id)
        if member is None:
            raise NotChatMemberError(chat_id=str(command.chat_id), user_id=user_id)

        chat.leave(user_id=user_id)
        await self.chat_repository.delete_member(member)
        await self.chat_repository.shift_member_count(chat.id, delta=-1)

        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()

        logger.info(
            "Leave chat", extra={"chat_id": str(chat.id), "leaved_id": user_id}
        )
