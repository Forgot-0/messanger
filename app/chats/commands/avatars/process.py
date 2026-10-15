import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import ChatAvatarValidationError
from app.chats.models.chat import ChatType
from app.chats.repositories.avatar_upload import ChatAvatarUploadRepository
from app.chats.repositories.chat import ChatRepository
from app.chats.services.chat_avatar import ChatAvatarService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.storage.exceptions import (
    ObjectChangedError,
    ObjectNotFoundError,
    ObjectTooLargeError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessChatAvatarCommand(BaseCommand):
    chat_id: str
    user_id: int
    upload_token: str


@dataclass(frozen=True)
class ProcessChatAvatarCommandHandler(BaseCommandHandler[ProcessChatAvatarCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    upload_repository: ChatAvatarUploadRepository
    avatar_service: ChatAvatarService
    event_bus: BaseEventBus

    async def handle(self, command: ProcessChatAvatarCommand) -> None:
        chat_id = UUID(command.chat_id)
        slot = await self.upload_repository.pop(UUID(command.upload_token))
        if slot is None or slot.chat_id != chat_id or slot.uploader_id != command.user_id:
            logger.warning(
                "Chat avatar upload slot is missing or foreign",
                extra={"chat_id": command.chat_id, "upload_token": command.upload_token},
            )
            return

        try:
            data = await self.avatar_service.load_validated(slot)
            rendered = await self.avatar_service.render(data)
        except (
            ChatAvatarValidationError,
            ObjectNotFoundError,
            ObjectChangedError,
            ObjectTooLargeError,
        ) as exc:
            logger.warning(
                "Chat avatar rejected",
                extra={
                    "chat_id": command.chat_id,
                    "upload_token": command.upload_token,
                    "error": exc.code,
                    "detail": exc.detail,
                },
            )
            await self.avatar_service.drop_pending(slot)
            return

        avatars = await self.avatar_service.upload_variants(chat_id, slot.upload_token, rendered)

        chat = await self.chat_repository.get_by_id(chat_id, with_for_update=True)
        if chat is None or chat.type == ChatType.DIRECT:
            await self.session.rollback()
            await self.avatar_service.delete_variants(avatars)
            await self.avatar_service.drop_pending(slot)
            return

        stale = dict(chat.avatars or {})
        chat.update_avatar(updated_by=command.user_id, avatars=avatars)

        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()

        await self.avatar_service.drop_pending(slot)
        await self.avatar_service.delete_variants(stale)

        logger.info(
            "Chat avatar updated",
            extra={"chat_id": command.chat_id, "user_id": command.user_id},
        )
