import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.config import chat_config
from app.chats.dtos.chats import ChatStateDTO
from app.chats.exceptions import NotFoundChatError, PinnedChatsLimitExceededError
from app.chats.repositories.chat import ChatRepository
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateChatStateCommand(BaseCommand):
    chat_id: UUID
    user_jwt_data: UserJWTData

    provided: frozenset[str] = field(default_factory=frozenset)
    pinned: bool | None = None
    archived: bool | None = None
    notifications_muted_until: datetime | None = None
    draft: str | None = None


@dataclass(frozen=True)
class UpdateChatStateCommandHandler(BaseCommandHandler[UpdateChatStateCommand, ChatStateDTO]):
    session: AsyncSession
    chat_repository: ChatRepository

    async def handle(self, command: UpdateChatStateCommand) -> ChatStateDTO:
        user_id = int(command.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(
            chat_id=command.chat_id, member_id=user_id, with_role=False
        )
        if member is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        if "pinned" in command.provided:
            pinned = bool(command.pinned)
            if pinned and not member.is_pinned:
                pinned_count = await self.chat_repository.count_pinned_chats(user_id)
                if pinned_count >= chat_config.MAX_PINNED_CHATS:
                    raise PinnedChatsLimitExceededError

            member.set_pinned(pinned)

        if "archived" in command.provided:
            member.set_archived(bool(command.archived))

        if "notifications_muted_until" in command.provided:
            member.mute_notifications(command.notifications_muted_until)

        if "draft" in command.provided:
            member.set_draft(command.draft)

        await self.session.commit()

        logger.info(
            "Chat state updated",
            extra={
                "chat_id": str(command.chat_id),
                "user_id": user_id,
                "provided": sorted(command.provided),
            },
        )

        return ChatStateDTO.model_validate(member)
