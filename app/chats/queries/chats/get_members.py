from dataclasses import dataclass
from uuid import UUID

from app.chats.dtos.members import ListMembers, MemberChatDTO, MemberPresenceDTO
from app.chats.exceptions import NotChatMemberError, NotFoundChatError
from app.chats.repositories.chat import ChatRepository
from app.chats.services.messages import MessageService
from app.chats.services.privacy import ChatPrivacyService
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData
from app.core.websocket.presence import PresenceService


@dataclass(frozen=True, kw_only=True)
class GetChatMembersQuery(BaseQuery):
    user_jwt_data: UserJWTData
    chat_id: UUID
    limit: int = 30
    cursor_user_id: int | None = None
    include_presence: bool = False


@dataclass(frozen=True)
class GetChatMembersQueryHandler(BaseQueryHandler[GetChatMembersQuery, ListMembers]):
    chat_repository: ChatRepository
    presence_service: PresenceService
    message_service: MessageService
    privacy_service: ChatPrivacyService

    async def handle(self, query: GetChatMembersQuery) -> ListMembers:
        requester_id = int(query.user_jwt_data.id)

        chat = await self.chat_repository.get_by_id(query.chat_id)
        if chat is None:
            raise NotFoundChatError(chat_id=str(query.chat_id))

        requester = await self.chat_repository.get_member_chat(
            query.chat_id, requester_id, with_role=False, with_profile=True
        )
        if requester is None or requester.is_banned:
            raise NotChatMemberError(chat_id=str(query.chat_id), user_id=requester_id)

        limit = min(max(query.limit, 1), 30)
        members = await self.chat_repository.get_chat_members(
            chat_id=query.chat_id,
            limit=limit,
            cursor_user_id=query.cursor_user_id,
        )
        page = members[:limit]
        user_ids = [int(member.user_id) for member in page]

        hidden_photos = await self.privacy_service.hidden_photos(requester_id, user_ids)

        presence: list[MemberPresenceDTO] = []
        if query.include_presence and user_ids:
            hidden_presence = await self.privacy_service.hidden_presence(requester_id, user_ids)
            online_by_user = await self.presence_service.get_online_status(user_ids)
            presence = [
                MemberPresenceDTO(
                    user_id=user_id,
                    is_online=(
                        online_by_user.get(user_id, False) and user_id not in hidden_presence
                    ),
                )
                for user_id in user_ids
            ]

        member_dtos = [MemberChatDTO.model_validate(member) for member in page]
        self.privacy_service.strip_avatars([dto.profile for dto in member_dtos], hidden_photos)
        await self.message_service.image_urls(
            [dto.profile for dto in member_dtos]
        )

        return ListMembers(
            members=member_dtos,
            has_next=len(members) > limit,
            next_user_id=page[-1].user_id if len(members) > limit and page else None,
            presence=presence,
        )
