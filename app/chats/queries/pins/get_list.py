from dataclasses import dataclass
from uuid import UUID

from app.chats.config import chat_config
from app.chats.dtos.messages import MessageDTO
from app.chats.dtos.pins import PinnedMessageDTO, PinnedMessagesDTO
from app.chats.exceptions import NotChatMemberError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.pinned_message import ChatPinnedMessageRepository
from app.chats.services.messages import MessageService
from app.chats.services.privacy import ChatPrivacyService
from app.chats.services.reaction_attach import ReactionAttachService
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData


@dataclass(frozen=True, kw_only=True)
class GetPinnedMessagesQuery(BaseQuery):
    user_jwt_data: UserJWTData
    chat_id: UUID
    limit: int = chat_config.PINNED_MESSAGES_PAGE_SIZE
    before_seq: int | None = None


@dataclass(frozen=True)
class GetPinnedMessagesQueryHandler(BaseQueryHandler[GetPinnedMessagesQuery, PinnedMessagesDTO]):
    chat_repository: ChatRepository
    pin_repository: ChatPinnedMessageRepository
    message_service: MessageService
    reaction_attach_service: ReactionAttachService
    privacy_service: ChatPrivacyService

    async def handle(self, query: GetPinnedMessagesQuery) -> PinnedMessagesDTO:
        user_id = int(query.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(query.chat_id, user_id, with_role=False)
        if member is None or member.is_banned:
            raise NotChatMemberError(chat_id=str(query.chat_id), user_id=user_id)

        limit = min(max(query.limit, 1), chat_config.PINNED_MESSAGES_MAX_PAGE_SIZE)
        rows = await self.pin_repository.get_page(
            chat_id=query.chat_id,
            limit=limit,
            before_seq=query.before_seq,
        )
        page = rows[:limit]
        has_next = len(rows) > limit

        message_dtos = [MessageDTO.model_validate(message) for _pin, message in page]
        await self.privacy_service.hide_avatars(user_id, MessageService.message_profiles(message_dtos))
        message_dtos = await self.message_service.attach_download_urls(message_dtos)
        message_dtos = await self.reaction_attach_service.attach(message_dtos, user_id)

        return PinnedMessagesDTO(
            items=[
                PinnedMessageDTO(message=dto, pinned_by=pin.pinned_by, pinned_at=pin.pinned_at)
                for (pin, _message), dto in zip(page, message_dtos, strict=True)
            ],
            total=await self.pin_repository.count(query.chat_id),
            has_next=has_next,
            next_cursor=page[-1][0].message_seq if has_next and page else None,
        )
