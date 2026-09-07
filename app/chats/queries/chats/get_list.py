from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.chats.dtos.chats import ChatDTO, ListChats
from app.chats.dtos.members import MemberChatDTO
from app.chats.dtos.messages import MessageDTO, ReadDetail
from app.chats.dtos.profiles import ChatProfileDTO
from app.chats.repositories.chat import ChatRepository
from app.chats.services.messages import MessageService
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData


@dataclass(frozen=True, kw_only=True)
class GetListChatUserQuery(BaseQuery):
    user_jwt_data: UserJWTData
    limit: int = 50
    last_chat_id: UUID | None = None
    last_activity_at: datetime | None = None


@dataclass(frozen=True)
class GetListChatUserQueryHandler(BaseQueryHandler[GetListChatUserQuery, ListChats]):
    chat_repository: ChatRepository
    message_service: MessageService

    async def handle(self, query: GetListChatUserQuery) -> ListChats:
        limit = min(max(query.limit, 1), 100)
        rows = await self.chat_repository.get_chats(
            user_id=int(query.user_jwt_data.id),
            limit=limit,
            last_activity_at=query.last_activity_at,
            chat_id=query.last_chat_id,
        )
        page = rows[:limit]

        chats = []
        profiles: list[ChatProfileDTO | None] = []
        for chat, member, read, message in page:
            me_dto = MemberChatDTO.model_validate(member)
            last_message = (
                MessageDTO.model_validate(message) if message is not None else None
            )

            profiles.append(me_dto.profile)
            if last_message is not None:
                profiles.append(last_message.profile)

            chats.append(ChatDTO(
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
                unread_count=(
                    max(0, chat.seq_counter - read.last_read_message_seq)
                    if read is not None
                    else chat.seq_counter
                ),
                me=me_dto,
                last_read=ReadDetail.model_validate(read) if read is not None else None,
                last_message=last_message,
            ))

        await self.message_service.attach_profile_urls(profiles)

        return ListChats(
            has_next=len(rows) > limit,
            chats=chats,
            next_date=page[-1][0].last_activity_at if len(rows) > limit and page else None,
            next_chat_id=page[-1][0].id if len(rows) > limit and page else None,
        )
