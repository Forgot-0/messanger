import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.chats import ChatDTO
from app.chats.exceptions import AccessDeniedChatError, NotFoundChatError
from app.chats.models.chat import ChatReactionsMode
from app.chats.repositories.chat import ChatRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateChatCommand(BaseCommand):
    chat_id: UUID
    name: str | None
    description: str | None
    is_public: bool | None
    user_jwt_data: UserJWTData
    admin_only: bool | None = None
    slow_mode_seconds: int | None = None
    permissions: dict[str, bool] | None = None
    reactions_mode: ChatReactionsMode | None = None
    allowed_reactions: list[str] | None = None


@dataclass(frozen=True)
class UpdateChatCommandHandler(BaseCommandHandler[UpdateChatCommand, ChatDTO]):
    sessions: AsyncSession
    chat_repository: ChatRepository
    access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: UpdateChatCommand) -> ChatDTO:
        chat = await self.chat_repository.get_by_id(chat_id=command.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(command.chat_id))

        user_id = int(command.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(
            chat_id=command.chat_id, member_id=user_id
        )

        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=member,
            must_permissions={"chat:update"}
        ):
            raise AccessDeniedChatError(
                chat_id=str(command.chat_id), requester_id=user_id
            )

        chat.update(
            updated_by=user_id,
            name=command.name,
            description=command.description,
            is_public=command.is_public,
            admin_only=command.admin_only,
            slow_mode_seconds=command.slow_mode_seconds,
            permissions=command.permissions,
            reactions_mode=command.reactions_mode,
            allowed_reactions=command.allowed_reactions,
        )

        await self.event_bus.publish(chat.pull_events())
        await self.sessions.commit()

        return ChatDTO.model_validate(chat)
