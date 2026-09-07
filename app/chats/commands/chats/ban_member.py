import logging
from dataclasses import dataclass
from datetime import datetime
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
class BanMemberCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    target_user_id: int

    banned_until: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True)
class BanMemberCommandHandler(BaseCommandHandler[BanMemberCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    chat_access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: BanMemberCommand) -> None:
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
            must_permissions={"member:ban"}
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=requester_id)

        target.ban(banned_by=requester_id, reason=command.reason, banned_until=command.banned_until)
        chat.ban_member(command.target_user_id, requester_id, target.is_banned)

        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()

        action = "banned" if target.is_banned else "unbanned"
        logger.info(
            "Member %s",
            action,
            extra={
                "chat_id": command.chat_id,
                "target": command.target_user_id,
                "by": requester_id,
            },
        )
