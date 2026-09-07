import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.reactions import build_reaction_event
from app.chats.exceptions import NotChatMemberError, NotFoundMessageError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.repositories.reaction import MessageReactionRepository
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class RemoveReactionCommand(BaseCommand):
    chat_id: UUID
    message_id: UUID
    emoji: str
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class RemoveReactionCommandHandler(BaseCommandHandler[RemoveReactionCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    message_repository: MessageRepository
    reaction_repository: MessageReactionRepository
    event_bus: BaseEventBus

    async def handle(self, command: RemoveReactionCommand) -> None:
        user_id = int(command.user_jwt_data.id)

        _chat, member = await self.chat_repository.get_chat_and_member(
            chat_id=command.chat_id, member_id=user_id
        )
        if member.is_banned:
            raise NotChatMemberError(chat_id=str(command.chat_id), user_id=user_id)

        message = await self.message_repository.get_by_id(command.message_id)
        if message is None or message.chat_id != command.chat_id:
            raise NotFoundMessageError(message_id=str(command.message_id))

        applied = await self.reaction_repository.remove_reaction(
            message_id=command.message_id,
            user_id=user_id,
            emoji=command.emoji,
        )
        if applied is None:
            return

        event = await build_reaction_event(
            self.reaction_repository,
            chat_id=command.chat_id,
            message_id=command.message_id,
            actor_id=user_id,
            action="remove",
        )
        await self.event_bus.publish([event])
        await self.session.commit()

        logger.info(
            "Reaction removed",
            extra={
                "chat_id": str(command.chat_id),
                "message_id": str(command.message_id),
                "user_id": user_id,
                "emoji": command.emoji,
            },
        )
