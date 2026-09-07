from dataclasses import dataclass
from uuid import UUID

from app.chats.dtos.chats import ChatDetailDTO
from app.chats.dtos.members import MemberChatDTO
from app.chats.exceptions import NotChatMemberError, NotFoundChatError
from app.chats.repositories.chat import ChatRepository
from app.chats.services.messages import MessageService
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData


@dataclass(frozen=True, kw_only=True)
class GetChatDetailQuery(BaseQuery):
    user_jwt_data: UserJWTData
    chat_id: UUID


@dataclass(frozen=True)
class GetChatDetailQueryHandler(BaseQueryHandler[GetChatDetailQuery, ChatDetailDTO]):
    chat_repository: ChatRepository
    message_service: MessageService

    async def handle(self, query: GetChatDetailQuery) -> ChatDetailDTO:
        user_id = int(query.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(query.chat_id, with_members=True)
        if chat is None:
            raise NotFoundChatError(chat_id=str(query.chat_id))

        member = await self.chat_repository.get_member_chat(
            query.chat_id, user_id, with_role=False
        )
        if member is None or member.is_banned:
            raise NotChatMemberError(chat_id=str(query.chat_id), user_id=user_id)

        member_dtos = [MemberChatDTO.model_validate(item) for item in chat.members]
        await self.message_service.attach_profile_urls(
            [dto.profile for dto in member_dtos]
        )

        return ChatDetailDTO(
            id=chat.id,
            seq_counter=chat.seq_counter,
            last_activity_at=chat.last_activity_at,
            type=chat.type,
            name=chat.name,
            description=chat.description,
            avatar_s3_key=chat.avatar_s3_key,
            is_public=chat.is_public,
            admin_only=chat.admin_only,
            slow_mode_seconds=chat.slow_mode_seconds,
            permissions=chat.permissions or {},
            created_by=chat.created_by,
            member_count=chat.member_count,
            members=member_dtos,
        )
