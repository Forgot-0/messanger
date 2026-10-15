import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import (
    AccessDeniedChatError,
    NotChatMemberError,
    NotFoundChatError,
)
from app.chats.models.chat_roles import ChatRoleId
from app.chats.repositories.chat import ChatRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransferChatOwnershipCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    new_owner_id: int


@dataclass(frozen=True)
class TransferChatOwnershipCommandHandler(BaseCommandHandler[TransferChatOwnershipCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    chat_access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: TransferChatOwnershipCommand) -> None:
        requester_id = int(command.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(command.chat_id, with_for_update=True)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        requester = await self.chat_repository.get_member_chat(command.chat_id, requester_id)
        if not self.chat_access_service.can_transfer_ownership(
            user_jwt_data=command.user_jwt_data,
            chat=chat,
            requester=requester,
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=requester_id)

        new_owner = await self.chat_repository.get_member_chat(command.chat_id, command.new_owner_id)
        if new_owner is None:
            raise NotChatMemberError(chat_id=str(command.chat_id), user_id=command.new_owner_id)

        previous_owner_id = chat.transfer_ownership(requester_id=requester_id, new_owner=new_owner)

        previous_owner = (
            requester
            if requester is not None and requester.user_id == previous_owner_id
            else await self.chat_repository.get_member_chat(command.chat_id, previous_owner_id)
        )
        if previous_owner is not None:
            previous_owner.role_id = ChatRoleId.ADMIN

        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()

        logger.info(
            "Chat ownership transferred",
            extra={
                "chat_id": command.chat_id,
                "previous_owner_id": previous_owner_id,
                "new_owner_id": command.new_owner_id,
                "by": requester_id,
            },
        )
