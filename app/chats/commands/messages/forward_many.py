import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.messages import ForwardedMessagesDTO, MessageDTO
from app.chats.exceptions import (
    AccessDeniedChatError,
    InvalidMessageError,
    NotChatMemberError,
    NotFoundChatError,
    NotFoundMessageError,
    SlowModeMultipleMessagesError,
)
from app.chats.models.chat import Chat
from app.chats.models.chat_members import ChatMember
from app.chats.models.message import Message, MessageType
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.services.access import ChatAccessService
from app.chats.services.messages import MessageService
from app.chats.services.privacy import ChatPrivacyService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ForwardMessagesCommand(BaseCommand):
    user_jwt_data: UserJWTData
    source_chat_id: UUID
    source_message_ids: list[UUID]
    target_chat_id: UUID
    hide_author: bool = False
    comment: str | None = None


@dataclass(frozen=True)
class ForwardMessagesCommandHandler(BaseCommandHandler[ForwardMessagesCommand, ForwardedMessagesDTO]):
    session: AsyncSession
    chat_repository: ChatRepository
    message_repository: MessageRepository
    chat_access_service: ChatAccessService
    message_service: MessageService
    privacy_service: ChatPrivacyService
    event_bus: BaseEventBus

    async def handle(self, command: ForwardMessagesCommand) -> ForwardedMessagesDTO:
        user_id = int(command.user_jwt_data.id)
        source_ids = list(dict.fromkeys(command.source_message_ids))

        source_member = await self.chat_repository.get_member_chat(command.source_chat_id, user_id)
        if source_member is None or source_member.is_banned:
            raise NotChatMemberError(chat_id=str(command.source_chat_id), user_id=user_id)

        if not await self.chat_access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=source_member,
            must_permissions={"message:read"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.source_chat_id), requester_id=user_id)

        sources = await self.message_repository.get_many_in_chat(command.source_chat_id, source_ids)
        if not sources:
            raise NotFoundMessageError(message_id=str(source_ids[0]))

        forwardable = [message for message in sources if message.is_forwardable]
        if not forwardable:
            raise InvalidMessageError(reason="selected messages have nothing to forward")

        target_chat, target_member = await self.chat_repository.get_chat_and_member(
            chat_id=command.target_chat_id, member_id=user_id
        )
        if not await self.chat_access_service.can_send_message(
            user_jwt_data=command.user_jwt_data,
            chat=target_chat,
            member=target_member,
        ):
            raise AccessDeniedChatError(chat_id=str(command.target_chat_id), requester_id=user_id)

        await self.privacy_service.ensure_can_message(target_chat, user_id)

        comment = command.comment.strip() if command.comment else None
        total = len(forwardable) + (1 if comment else 0)
        await self._ensure_slow_mode(target_chat, target_member, user_id, total)

        last_seq = await self.chat_repository.allocate_message_seq(
            chat_id=command.target_chat_id,
            message_date=now_utc(),
            count=total,
        )
        if last_seq is None:
            raise NotFoundChatError(chat_id=str(command.target_chat_id))

        created = self._build_messages(
            command, user_id, forwardable, comment, first_seq=last_seq - total + 1
        )
        await self.message_repository.create_many(created)
        await self.event_bus.publish([event for message in created for event in message.pull_events()])
        await self.session.commit()

        logger.info(
            "Messages forwarded",
            extra={
                "source_chat_id": command.source_chat_id,
                "target_chat_id": command.target_chat_id,
                "requested": len(source_ids),
                "forwarded": len(forwardable),
                "hide_author": command.hide_author,
                "by": user_id,
            },
        )

        dtos = await self.message_service.attach_download_urls(
            [MessageDTO.model_validate(message) for message in created]
        )
        return ForwardedMessagesDTO(messages=dtos)

    @staticmethod
    def _build_messages(
        command: ForwardMessagesCommand,
        user_id: int,
        sources: list[Message],
        comment: str | None,
        first_seq: int,
    ) -> list[Message]:
        seqs = iter(range(first_seq, first_seq + len(sources) + (1 if comment else 0)))
        created: list[Message] = []

        if comment:
            created.append(Message.create(
                sender_id=user_id,
                chat_id=command.target_chat_id,
                seq=next(seqs),
                content=comment,
                message_type=MessageType.TEXT,
                notify=False,
            ))

        for index, source in enumerate(sources):
            created.append(Message.create_forward(
                source=source,
                sender_id=user_id,
                chat_id=command.target_chat_id,
                seq=next(seqs),
                hide_author=command.hide_author,
                notify=index == len(sources) - 1,
            ))

        return created

    async def _ensure_slow_mode(
        self,
        chat: Chat,
        member: ChatMember,
        user_id: int,
        total: int,
    ) -> None:
        if chat.slow_mode_seconds <= 0 or self.chat_access_service.can_bypass_slow_mode(member):
            return

        if total > 1:
            raise SlowModeMultipleMessagesError(chat_id=str(chat.id), count=total)

        await self.message_service.is_slow(chat=chat, user_id=user_id, member=member)
