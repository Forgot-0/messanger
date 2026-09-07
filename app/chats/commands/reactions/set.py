import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.reactions import build_reaction_event
from app.chats.config import chat_config
from app.chats.exceptions import (
    NotChatMemberError,
    NotFoundMessageError,
    TooManyReactionsError,
)
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.repositories.reaction import MessageReactionRepository
from app.chats.services.reaction_policy import ReactionPolicy
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SetReactionCommand(BaseCommand):
    chat_id: UUID
    message_id: UUID
    emoji: str
    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class SetReactionCommandHandler(BaseCommandHandler[SetReactionCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    message_repository: MessageRepository
    reaction_repository: MessageReactionRepository
    reaction_policy: ReactionPolicy
    event_bus: BaseEventBus

    async def handle(self, command: SetReactionCommand) -> None:
        user_id = int(command.user_jwt_data.id)

        chat, member = await self.chat_repository.get_chat_and_member(
            chat_id=command.chat_id, member_id=user_id
        )
        if member.is_banned:
            raise NotChatMemberError(chat_id=str(command.chat_id), user_id=user_id)

        message = await self.message_repository.get_by_id(command.message_id)
        if message is None or message.chat_id != command.chat_id:
            raise NotFoundMessageError(message_id=str(command.message_id))

        try:
            self.reaction_policy.validate(chat, member, command.emoji)
        except Exception:
            raise

        existing = await self.reaction_repository.list_user_emojis(
            command.message_id, user_id
        )
        if command.emoji not in existing:
            if len(existing) >= chat_config.MAX_REACTIONS_PER_USER_PER_MESSAGE:
                raise TooManyReactionsError(
                    limit=chat_config.MAX_REACTIONS_PER_USER_PER_MESSAGE, scope="user"
                )
            distinct = await self.reaction_repository.count_distinct_emojis(
                command.message_id
            )
            if distinct >= chat_config.MAX_DISTINCT_REACTIONS_PER_MESSAGE:
                raise TooManyReactionsError(
                    limit=chat_config.MAX_DISTINCT_REACTIONS_PER_MESSAGE, scope="message"
                )

        applied = await self.reaction_repository.add_reaction(
            chat_id=command.chat_id,
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
            action="add",
        )
        await self.event_bus.publish([event])
        await self.session.commit()

        logger.info(
            "Reaction added",
            extra={
                "chat_id": str(command.chat_id),
                "message_id": str(command.message_id),
                "user_id": user_id,
                "emoji": command.emoji,
            },
        )
