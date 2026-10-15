import re
from dataclasses import dataclass

from app.chats.config import chat_config
from app.chats.dtos.chats import ChatPreviewDTO, PublicChatSearchDTO
from app.chats.repositories.chat import ChatRepository
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData

_TERM_SEPARATOR = re.compile(r"\W+", re.UNICODE)
_USERNAME_PREFIX = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True, kw_only=True)
class SearchPublicChatsQuery(BaseQuery):
    user_jwt_data: UserJWTData
    q: str
    limit: int = chat_config.PUBLIC_CHAT_SEARCH_LIMIT


@dataclass(frozen=True)
class SearchPublicChatsQueryHandler(BaseQueryHandler[SearchPublicChatsQuery, PublicChatSearchDTO]):
    chat_repository: ChatRepository

    async def handle(self, query: SearchPublicChatsQuery) -> PublicChatSearchDTO:
        limit = min(max(query.limit, 1), chat_config.PUBLIC_CHAT_SEARCH_MAX_LIMIT)
        by_username_only = query.q.strip().startswith("@")
        normalized = query.q.strip().removeprefix("@").casefold()

        username_prefix = normalized if _USERNAME_PREFIX.fullmatch(normalized) else None

        tsquery = None
        if not by_username_only:
            terms = [term for term in _TERM_SEPARATOR.split(normalized) if term]
            terms = terms[:chat_config.PUBLIC_CHAT_SEARCH_MAX_TERMS]
            if terms:
                *exact, last = terms
                tsquery = " & ".join([*exact, f"{last}:*"])

        chats = await self.chat_repository.search_public(
            username_prefix=username_prefix,
            tsquery=tsquery,
            exact_username=username_prefix,
            limit=limit,
        )
        if not chats:
            return PublicChatSearchDTO(items=[])

        member_of = await self.chat_repository.member_chat_ids(
            int(query.user_jwt_data.id), [chat.id for chat in chats]
        )

        items = []
        for chat in chats:
            dto = ChatPreviewDTO.model_validate(chat)
            dto.is_member = chat.id in member_of
            items.append(dto)

        return PublicChatSearchDTO(items=items)
