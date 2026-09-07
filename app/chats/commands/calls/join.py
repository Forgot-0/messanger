import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.dtos.livekit import JoinTokenDTO
from app.chats.exceptions import AccessDeniedChatError, NotChatMemberError, NotFoundChatError
from app.chats.models.chat import ChatType
from app.chats.repositories.chat import ChatRepository
from app.chats.services.livekit_service import LiveKitService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JoinCallCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID


@dataclass(frozen=True)
class JoinCallCommandHandler(BaseCommandHandler[JoinCallCommand, JoinTokenDTO]):
    session: AsyncSession
    chat_repository: ChatRepository
    livekit_service: LiveKitService
    event_bus: BaseEventBus

    async def handle(self, command: JoinCallCommand) -> JoinTokenDTO:
        user_id = int(command.user_jwt_data.id)
        username = command.user_jwt_data.username

        member = await self.chat_repository.get_member_chat(command.chat_id, user_id)
        if member is None:
            raise NotChatMemberError(chat_id=str(command.chat_id), user_id=user_id)

        chat = await self.chat_repository.get_by_id(command.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        if (
            chat.type == ChatType.SUPERGROUP or
            chat.type == ChatType.CHANNEL or
            chat.member_count >= chat_config.ROOM_MAX_PARTICIPANTS
        ):
            raise AccessDeniedChatError(chat_id=str(chat.id), requester_id=user_id)

        token = self.livekit_service.generate_join_token(
            slug=str(chat.id),
            user_id=str(user_id),
            username=username,
        )

        await self.session.commit()
        logger.info(
            "User joined call",
            extra={"chat_id": command.chat_id, "user_id": user_id, "slug": str(chat.id)},
        )

        return JoinTokenDTO(
            token=token,
            slug=str(chat.id),
            livekit_url=self.livekit_service.url,
        )
