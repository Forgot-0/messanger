import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import AccessDeniedChatError, NotFoundChatError
from app.chats.repositories.chat import ChatRepository
from app.chats.services.access import ChatAccessService
from app.chats.services.chat_avatar import ChatAvatarService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoveChatAvatarCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID


@dataclass(frozen=True)
class RemoveChatAvatarCommandHandler(BaseCommandHandler[RemoveChatAvatarCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    access_service: ChatAccessService
    avatar_service: ChatAvatarService
    event_bus: BaseEventBus

    async def handle(self, command: RemoveChatAvatarCommand) -> None:
        user_id = int(command.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(command.chat_id, with_for_update=True)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        member = await self.chat_repository.get_member_chat(command.chat_id, user_id)
        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=member,
            must_permissions={"chat:update"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=user_id)

        if not chat.avatars and chat.avatar_s3_key is None:
            return

        stale = dict(chat.avatars or {})
        chat.update_avatar(updated_by=user_id, avatars={})

        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()

        await self.avatar_service.delete_variants(stale)

        logger.info("Chat avatar removed", extra={"chat_id": str(chat.id), "by": user_id})
