from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.chats.config import chat_config
from app.chats.dtos.messages import MessageReadDTO, MessageReadsDTO
from app.chats.dtos.profiles import ChatProfileDTO
from app.chats.exceptions import (
    AccessDeniedChatError,
    NotChatMemberError,
    NotFoundChatError,
    NotFoundMessageError,
    ReadReceiptsUnavailableError,
    ReadReceiptsUnavailableReason,
)
from app.chats.models.chat import ChatType
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.repositories.reads import ReadReceiptRepository
from app.chats.services.messages import MessageService
from app.chats.services.privacy import ChatPrivacyService
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc


@dataclass(frozen=True, kw_only=True)
class GetMessageReadsQuery(BaseQuery):
    user_jwt_data: UserJWTData
    chat_id: UUID
    message_id: UUID


@dataclass(frozen=True)
class GetMessageReadsQueryHandler(BaseQueryHandler[GetMessageReadsQuery, MessageReadsDTO]):
    chat_repository: ChatRepository
    message_repository: MessageRepository
    read_receipt_repository: ReadReceiptRepository
    message_service: MessageService
    privacy_service: ChatPrivacyService

    async def handle(self, query: GetMessageReadsQuery) -> MessageReadsDTO:
        user_id = int(query.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(query.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(query.chat_id))

        member = await self.chat_repository.get_member_chat(query.chat_id, user_id, with_role=False)
        if member is None or member.is_banned:
            raise NotChatMemberError(chat_id=str(query.chat_id), user_id=user_id)

        message = await self.message_repository.get_by_id(query.message_id)
        if message is None or message.chat_id != query.chat_id:
            raise NotFoundMessageError(message_id=str(query.message_id))

        if message.author_id != user_id:
            raise AccessDeniedChatError(chat_id=str(query.chat_id), requester_id=user_id)

        if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            raise ReadReceiptsUnavailableError(
                chat_id=str(chat.id), reason=ReadReceiptsUnavailableReason.CHAT_TYPE
            )

        if not chat.is_small_group:
            raise ReadReceiptsUnavailableError(
                chat_id=str(chat.id), reason=ReadReceiptsUnavailableReason.CHAT_TOO_LARGE
            )

        if message.created_at < now_utc() - timedelta(days=chat_config.READ_MARKS_RETENTION_DAYS):
            raise ReadReceiptsUnavailableError(
                chat_id=str(chat.id), reason=ReadReceiptsUnavailableReason.MESSAGE_TOO_OLD
            )

        readers = await self.read_receipt_repository.get_message_readers(
            chat_id=query.chat_id,
            message_seq=message.seq,
            exclude_user_id=user_id,
            limit=chat_config.READ_MARKS_MAX_MEMBERS,
        )

        dtos = [
            MessageReadDTO(
                user_id=reader.user_id,
                read_at=reader.read_at,
                profile=ChatProfileDTO.model_validate(reader.profile) if reader.profile else None,
            )
            for reader in readers
        ]
        profiles = [dto.profile for dto in dtos]
        await self.privacy_service.hide_avatars(user_id, profiles)
        await self.message_service.image_urls(profiles)

        return MessageReadsDTO(message_id=message.id, readers=dtos)
