import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.invites import ChatInviteLinkDTO
from app.chats.exceptions import AccessDeniedChatError, NotFoundInviteLinkError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.invite import ChatInviteLinkRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RevokeInviteLinkCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    invite_id: UUID


@dataclass(frozen=True)
class RevokeInviteLinkCommandHandler(BaseCommandHandler[RevokeInviteLinkCommand, ChatInviteLinkDTO]):
    session: AsyncSession
    chat_repository: ChatRepository
    invite_repository: ChatInviteLinkRepository
    access_service: ChatAccessService

    async def handle(self, command: RevokeInviteLinkCommand) -> ChatInviteLinkDTO:
        user_id = int(command.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(command.chat_id, user_id)
        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=member,
            must_permissions={"member:invite"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=user_id)

        invite = await self.invite_repository.get_by_id(command.invite_id)
        if invite is None or invite.chat_id != command.chat_id:
            raise NotFoundInviteLinkError(invite=str(command.invite_id))

        if not invite.is_revoked:
            invite.revoke()
            await self.session.commit()

            logger.info(
                "Invite link revoked",
                extra={"chat_id": str(command.chat_id), "invite_id": str(invite.id), "by": user_id},
            )

        return ChatInviteLinkDTO.model_validate(invite)
