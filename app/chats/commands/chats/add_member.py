import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import (
    AccessDeniedChatError,
    AlreadyMemberError,
    MemberLimitExceededError,
)
from app.chats.models.chat import Chat
from app.chats.repositories.chat import ChatRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AddMemberCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    target_user_id: int
    role_id: int


@dataclass(frozen=True)
class AddMemberCommandHandler(BaseCommandHandler[AddMemberCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    chat_access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: AddMemberCommand) -> None:
        requester_id = int(command.user_jwt_data.id)
        chat, requester = await self.chat_repository.get_chat_and_member(
            chat_id=command.chat_id, member_id=requester_id
        )

        if not await self.chat_access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=requester,
            must_permissions={"member:invite"}
        ):
            raise AccessDeniedChatError(chat_id=str(chat.id), requester_id=requester_id)

        self.chat_access_service.ensure_can_assign_role(
            user_jwt_data=command.user_jwt_data,
            requester=requester,
            chat_id=command.chat_id,
            role_id=command.role_id,
        )

        existing = await self.chat_repository.get_member_chat(command.chat_id, command.target_user_id)
        if existing:
            raise AlreadyMemberError(user_id=command.target_user_id, chat_id=str(command.chat_id))

        limit = Chat.member_limit(chat.type)
        if await self.chat_repository.shift_member_count(chat.id, delta=1, limit=limit) is None:
            raise MemberLimitExceededError(limit=limit)

        chat.add_member(
            member_id=command.target_user_id,
            role_id=command.role_id,
        )

        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()

        logger.info(
            "Member added to chat",
            extra={"chat_id": command.chat_id, "user_id": command.target_user_id},
        )
