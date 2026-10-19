import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.chats import ChatDTO
from app.chats.dtos.join_requests import (
    ChatJoinRequestDTO,
    JoinChatResultDTO,
    JoinResultStatus,
)
from app.chats.exceptions import (
    AccessDeniedChatError,
    AlreadyMemberError,
    InviteLinkExpiredError,
    InviteLinkInactiveReason,
    MemberLimitExceededError,
    NotFoundInviteLinkError,
)
from app.chats.models.chat import Chat, ChatType
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.invite import ChatInviteLinkRepository
from app.chats.services.join_requests import ChatJoinRequestService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JoinChatByInviteCommand(BaseCommand):
    user_jwt_data: UserJWTData
    code: str


@dataclass(frozen=True)
class JoinChatByInviteCommandHandler(
    BaseCommandHandler[JoinChatByInviteCommand, JoinChatResultDTO]
):
    session: AsyncSession
    chat_repository: ChatRepository
    invite_repository: ChatInviteLinkRepository
    join_request_service: ChatJoinRequestService
    event_bus: BaseEventBus

    async def handle(self, command: JoinChatByInviteCommand) -> JoinChatResultDTO:
        user_id = int(command.user_jwt_data.id)

        invite = await self.invite_repository.get_by_code(command.code)
        if invite is None:
            raise NotFoundInviteLinkError(invite=command.code)

        reason = invite.inactive_reason
        if reason is not None:
            raise InviteLinkExpiredError(reason=reason)

        chat = await self.chat_repository.get_by_id(invite.chat_id)
        if chat is None or chat.type == ChatType.DIRECT:
            raise NotFoundInviteLinkError(invite=command.code)

        if invite.creates_join_request:
            request = await self.join_request_service.submit(
                chat=chat, user_id=user_id, invite_link_id=invite.id
            )

            await self.event_bus.publish(request.pull_events())
            await self.session.commit()

            logger.info(
                "Join request created by invite link",
                extra={
                    "chat_id": str(chat.id),
                    "user_id": user_id,
                    "invite_id": str(invite.id),
                },
            )
            return JoinChatResultDTO(
                status=JoinResultStatus.REQUESTED,
                join_request=ChatJoinRequestDTO.model_validate(request),
            )

        existing = await self.chat_repository.get_member_chat(chat.id, user_id, with_role=False)
        if existing is not None:
            if existing.is_banned:
                raise AccessDeniedChatError(chat_id=str(chat.id), requester_id=user_id)
            raise AlreadyMemberError(user_id=user_id, chat_id=str(chat.id))

        if await self.invite_repository.consume(invite.id) is None:
            await self.session.refresh(invite)
            raise InviteLinkExpiredError(
                reason=invite.inactive_reason or InviteLinkInactiveReason.USAGE_LIMIT_REACHED
            )

        limit = Chat.member_limit(chat.type)
        member_count = await self.chat_repository.shift_member_count(chat.id, delta=1, limit=limit)
        if member_count is None:
            raise MemberLimitExceededError(limit=limit)

        chat.add_member(user_id, role_id=Chat.default_member_role(chat.type))

        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()

        logger.info(
            "User joined chat by invite link",
            extra={"chat_id": str(chat.id), "user_id": user_id, "invite_id": str(invite.id)},
        )
        return JoinChatResultDTO(
            status=JoinResultStatus.JOINED, chat=ChatDTO.model_validate(chat)
        )
