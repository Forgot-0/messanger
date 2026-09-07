from dataclasses import dataclass
from uuid import UUID

from app.chats.dtos.messages import MessageDTO, MessagesDTO
from app.chats.exceptions import NotChatMemberError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.message import MessageRepository
from app.chats.services.messages import MessageService
from app.chats.services.reaction_attach import ReactionAttachService
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData


@dataclass(frozen=True)
class GetMessagesQuery(BaseQuery):
    user_jwt_data: UserJWTData
    chat_id: UUID
    limit: int = 30
    cursor_message_seq: int | None = None


@dataclass(frozen=True)
class GetMessagesQueryHandler(BaseQueryHandler[GetMessagesQuery, MessagesDTO]):
    chat_repository: ChatRepository
    message_repository: MessageRepository
    message_service: MessageService
    reaction_attach_service: ReactionAttachService

    async def handle(self, query: GetMessagesQuery) -> MessagesDTO:
        user_id = int(query.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(query.chat_id, user_id, with_role=False)
        if not member or member.is_banned:
            raise NotChatMemberError(chat_id=str(query.chat_id), user_id=user_id)

        limit = min(max(query.limit, 1), 100)
        messages = await self.message_repository.get_paginated_chat_messages(
            chat_id=query.chat_id,
            cursor_seq=query.cursor_message_seq,
            limit=limit,
            direction="backward",
        )
        page = messages[:limit]
        message_dtos = [MessageDTO.model_validate(msg) for msg in page]
        message_dtos = await self.message_service.attach_download_urls(message_dtos)
        message_dtos = await self.reaction_attach_service.attach(message_dtos, user_id)

        return MessagesDTO(
            messages=message_dtos,
            has_next=len(messages) > limit,
            next_cursor=page[-1].seq if len(messages) > limit and page else None,
        )
