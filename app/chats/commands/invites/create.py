import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.dtos.invites import ChatInviteLinkDTO
from app.chats.exceptions import (
    AccessDeniedChatError,
    InvalidInviteLinkError,
    InviteLinksLimitExceededError,
    NotFoundChatError,
)
from app.chats.models.chat import ChatType
from app.chats.models.invite import ChatInviteLink
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.invite import ChatInviteLinkRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreateInviteLinkCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    name: str | None = None
    expires_at: datetime | None = None
    usage_limit: int | None = None


@dataclass(frozen=True)
class CreateInviteLinkCommandHandler(BaseCommandHandler[CreateInviteLinkCommand, ChatInviteLinkDTO]):
    session: AsyncSession
    chat_repository: ChatRepository
    invite_repository: ChatInviteLinkRepository
    access_service: ChatAccessService

    async def handle(self, command: CreateInviteLinkCommand) -> ChatInviteLinkDTO:
        user_id = int(command.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(command.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        member = await self.chat_repository.get_member_chat(command.chat_id, user_id)
        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=member,
            must_permissions={"member:invite"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=user_id)

        if chat.type == ChatType.DIRECT:
            raise InvalidInviteLinkError(reason="direct_chat")

        if (
            await self.invite_repository.count_not_revoked(chat.id)
            >= chat_config.MAX_INVITE_LINKS_PER_CHAT
        ):
            raise InviteLinksLimitExceededError(limit=chat_config.MAX_INVITE_LINKS_PER_CHAT)

        invite = ChatInviteLink.create(
            chat_id=chat.id,
            created_by=user_id,
            name=command.name,
            expires_at=command.expires_at,
            usage_limit=command.usage_limit,
        )
        await self.invite_repository.create(invite)
        await self.session.commit()

        logger.info(
            "Invite link created",
            extra={"chat_id": str(chat.id), "invite_id": str(invite.id), "by": user_id},
        )
        return ChatInviteLinkDTO.model_validate(invite)
