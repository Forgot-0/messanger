import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import (
    AccessDeniedChatError,
    NotChatMemberError,
    NotFoundChatError,
)
from app.chats.repositories.chat import ChatRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnmuteMemberCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    target_user_id: int


@dataclass(frozen=True)
class UnmuteMemberCommandHandler(BaseCommandHandler[UnmuteMemberCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    chat_access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: UnmuteMemberCommand) -> None:
        requester_id = int(command.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(command.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        requester = await self.chat_repository.get_member_chat(command.chat_id, requester_id)

        target = await self.chat_repository.get_member_chat(command.chat_id, command.target_user_id)
        if target is None:
            raise NotChatMemberError(chat_id=str(command.chat_id), user_id=command.target_user_id)

        if not await self.chat_access_service.update_member(
            user_jwt_data=command.user_jwt_data,
            requester=requester,
            target=target,
            must_permissions={"member:mute"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=requester_id)

        if not target.is_muted:
            return

        target.unmute()
        chat.mute_member(target, requester_id=requester_id)

        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()

        logger.info(
            "Member unmuted",
            extra={"chat_id": command.chat_id, "target": command.target_user_id, "by": requester_id},
        )
