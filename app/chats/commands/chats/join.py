import logging
from dataclasses import dataclass
from uuid import UUID

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
    MemberLimitExceededError,
    NotFoundChatError,
)
from app.chats.models.chat import Chat, ChatType
from app.chats.repositories.chat import ChatRepository
from app.chats.services.join_requests import ChatJoinRequestService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JoinChatCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID


@dataclass(frozen=True)
class JoinChatCommandHandler(BaseCommandHandler[JoinChatCommand, JoinChatResultDTO]):
    session: AsyncSession
    chat_repository: ChatRepository
    join_request_service: ChatJoinRequestService
    event_bus: BaseEventBus

    async def handle(self, command: JoinChatCommand) -> JoinChatResultDTO:
        user_id = int(command.user_jwt_data.id)
        chat = await self.chat_repository.get_by_id(command.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        if chat.type == ChatType.DIRECT or not chat.is_public:
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=user_id)

        if chat.join_by_request:
            request = await self.join_request_service.submit(chat=chat, user_id=user_id)

            await self.event_bus.publish(request.pull_events())
            await self.session.commit()

            logger.info(
                "Join request created for public chat",
                extra={"chat_id": str(chat.id), "user_id": user_id},
            )
            return JoinChatResultDTO(
                status=JoinResultStatus.REQUESTED,
                join_request=ChatJoinRequestDTO.model_validate(request),
            )

        existing = await self.chat_repository.get_member_chat(command.chat_id, user_id, with_role=False)
        if existing is not None:
            raise AlreadyMemberError(user_id=user_id, chat_id=str(command.chat_id))

        limit = Chat.member_limit(chat.type)
        if await self.chat_repository.shift_member_count(chat.id, delta=1, limit=limit) is None:
            raise MemberLimitExceededError(limit=limit)

        chat.add_member(user_id, role_id=Chat.default_member_role(chat.type))

        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()
        logger.info("User joined public chat", extra={"chat_id": command.chat_id, "user_id": user_id})

        return JoinChatResultDTO(
            status=JoinResultStatus.JOINED, chat=ChatDTO.model_validate(chat)
        )
