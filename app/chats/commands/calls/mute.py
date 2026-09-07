import logging
from dataclasses import dataclass
from uuid import UUID

from app.chats.exceptions import (
    AccessDeniedChatError,
    NotChatMemberError,
)
from app.chats.repositories.chat import ChatRepository
from app.chats.services.access import ChatAccessService
from app.chats.services.livekit_service import LiveKitService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MuteParticipantCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    target_user_id: int
    muted: bool = True


@dataclass(frozen=True)
class MuteParticipantCommandHandler(BaseCommandHandler[MuteParticipantCommand, None]):
    chat_repository: ChatRepository
    chat_access_service: ChatAccessService
    livekit_service: LiveKitService

    async def handle(self, command: MuteParticipantCommand) -> None:
        requester_id = int(command.user_jwt_data.id)

        requester = await self.chat_repository.get_member_chat(
            command.chat_id, requester_id
        )
        if requester is None:
            raise NotChatMemberError(chat_id=str(command.chat_id), user_id=requester_id)

        target = await self.chat_repository.get_member_chat(
            command.chat_id, command.target_user_id
        )
        if target is None:
            raise NotChatMemberError(chat_id=str(command.chat_id), user_id=command.target_user_id)

        if not await self.chat_access_service.update_member(
            user_jwt_data=command.user_jwt_data,
            requester=requester,
            target=target,
            must_permissions={"call:mute_member"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=requester_id)

        await self.livekit_service.mute_participant(
            slug=str(command.chat_id),
            identity=str(command.target_user_id),
            muted=command.muted,
        )

        action = "muted" if command.muted else "unmuted"
        logger.info(
            "Call participant %s",
            action,
            extra={
                "chat_id": command.chat_id,
                "target": command.target_user_id,
                "by": requester_id,
            },
        )
