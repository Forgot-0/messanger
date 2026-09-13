import re
from dataclasses import dataclass
from uuid import UUID

from app.chats.config import chat_config
from app.chats.dtos.messages import MessageDTO
from app.chats.dtos.search import MessageSearchDTO, MessageSearchItemDTO, SearchChatPreviewDTO
from app.chats.repositories.message import MessageRepository
from app.chats.services.messages import AvatarHolder, MessageService
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData

_TERM_SEPARATOR = re.compile(r"\W+", re.UNICODE)

@dataclass(frozen=True, kw_only=True)
class SearchMessagesQuery(BaseQuery):
    user_jwt_data: UserJWTData
    q: str
    chat_id: UUID | None = None
    limit: int = chat_config.MESSAGE_SEARCH_LIMIT
    last_message_id: UUID | None = None


@dataclass(frozen=True)
class SearchMessagesQueryHandler(BaseQueryHandler[SearchMessagesQuery, MessageSearchDTO]):
    message_repository: MessageRepository
    message_service: MessageService

    async def handle(self, query: SearchMessagesQuery) -> MessageSearchDTO:
        limit = min(max(query.limit, 1), chat_config.MESSAGE_SEARCH_MAX_LIMIT)

        terms = [term for term in _TERM_SEPARATOR.split(query.q.casefold()) if term]
        if not terms:
            return MessageSearchDTO(has_next=False, items=[], next_message_id=None)

        terms = terms[:chat_config.MESSAGE_SEARCH_MAX_TERMS]
        *exact, last = terms
        tsquery = " & ".join([*exact, f"{last}:*"])

        rows = await self.message_repository.search_visible(
            user_id=int(query.user_jwt_data.id),
            tsquery=tsquery,
            limit=limit,
            chat_id=query.chat_id,
            last_message_id=query.last_message_id,
        )
        page = rows[:limit]

        items: list[MessageSearchItemDTO] = []
        avatars: list[AvatarHolder | None] = []
        for message, chat in page:
            message_dto = MessageDTO.model_validate(message)
            chat_dto = SearchChatPreviewDTO.model_validate(chat)

            avatars.append(message_dto.profile)
            avatars.append(chat_dto)

            items.append(MessageSearchItemDTO(message=message_dto, chat=chat_dto))

        await self.message_service.image_urls(avatars)

        has_next = len(rows) > limit
        return MessageSearchDTO(
            has_next=has_next,
            items=items,
            next_message_id=page[-1][0].id if has_next and page else None,
        )
