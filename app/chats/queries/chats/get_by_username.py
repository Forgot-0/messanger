from dataclasses import dataclass

from app.chats.dtos.chats import ChatPreviewDTO
from app.chats.exceptions import NotFoundChatUsernameError
from app.chats.repositories.chat import ChatRepository
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData


@dataclass(frozen=True, kw_only=True)
class GetChatByUsernameQuery(BaseQuery):
    user_jwt_data: UserJWTData
    username: str


@dataclass(frozen=True)
class GetChatByUsernameQueryHandler(BaseQueryHandler[GetChatByUsernameQuery, ChatPreviewDTO]):
    chat_repository: ChatRepository

    async def handle(self, query: GetChatByUsernameQuery) -> ChatPreviewDTO:
        username = query.username.strip().removeprefix("@")
        chat = await self.chat_repository.get_by_username(username) if username else None

        if chat is None or not chat.is_public:
            raise NotFoundChatUsernameError(username=query.username)

        member_of = await self.chat_repository.member_chat_ids(
            int(query.user_jwt_data.id), [chat.id]
        )

        dto = ChatPreviewDTO.model_validate(chat)
        dto.is_member = chat.id in member_of
        return dto
