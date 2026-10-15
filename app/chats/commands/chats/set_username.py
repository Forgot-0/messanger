import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.chats import ChatDTO
from app.chats.exceptions import (
    AccessDeniedChatError,
    ChatUsernameTakenError,
    NotFoundChatError,
)
from app.chats.models.chat import Chat
from app.chats.repositories.chat import ChatRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SetChatUsernameCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    username: str | None


@dataclass(frozen=True)
class SetChatUsernameCommandHandler(BaseCommandHandler[SetChatUsernameCommand, ChatDTO]):
    session: AsyncSession
    chat_repository: ChatRepository
    access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: SetChatUsernameCommand) -> ChatDTO:
        user_id = int(command.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(command.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        member = await self.chat_repository.get_member_chat(command.chat_id, user_id)
        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=member,
            must_permissions={"chat:update"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=user_id)

        username = (
            Chat.validate_username(command.username) if command.username is not None else None
        )
        if username == chat.username:
            return ChatDTO.model_validate(chat)

        if username is not None:
            occupied = await self.chat_repository.get_by_username(username)
            if occupied is not None and occupied.id != chat.id:
                raise ChatUsernameTakenError(username=username)

        chat.set_username(updated_by=user_id, username=username)
        await self.event_bus.publish(chat.pull_events())

        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if "username" in str(exc.orig):
                raise ChatUsernameTakenError(username=username or "") from exc
            raise

        logger.info(
            "Chat username changed",
            extra={"chat_id": str(chat.id), "username": chat.username, "by": user_id},
        )
        return ChatDTO.model_validate(chat)
