from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.chats.config import chat_config
from app.chats.dtos.join_requests import ChatJoinRequestDTO, ListJoinRequests
from app.chats.dtos.profiles import ChatProfileDTO
from app.chats.exceptions import AccessDeniedChatError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.join_request import ChatJoinRequestRepository
from app.chats.services.access import ChatAccessService
from app.chats.services.messages import MessageService
from app.chats.services.privacy import ChatPrivacyService
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData


@dataclass(frozen=True, kw_only=True)
class GetJoinRequestsQuery(BaseQuery):
    user_jwt_data: UserJWTData
    chat_id: UUID
    limit: int = chat_config.JOIN_REQUESTS_PAGE_SIZE
    last_requested_at: datetime | None = None
    last_user_id: int | None = None


@dataclass(frozen=True)
class GetJoinRequestsQueryHandler(BaseQueryHandler[GetJoinRequestsQuery, ListJoinRequests]):
    chat_repository: ChatRepository
    join_request_repository: ChatJoinRequestRepository
    access_service: ChatAccessService
    message_service: MessageService
    privacy_service: ChatPrivacyService

    async def handle(self, query: GetJoinRequestsQuery) -> ListJoinRequests:
        user_id = int(query.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(query.chat_id, user_id)
        if not await self.access_service.has_permissions(
            user_jwt_data=query.user_jwt_data,
            member=member,
            must_permissions={"member:invite"},
        ):
            raise AccessDeniedChatError(chat_id=str(query.chat_id), requester_id=user_id)

        limit = min(max(query.limit, 1), chat_config.JOIN_REQUESTS_MAX_PAGE_SIZE)
        rows = await self.join_request_repository.list_pending(
            chat_id=query.chat_id,
            limit=limit,
            last_requested_at=query.last_requested_at,
            last_user_id=query.last_user_id,
        )
        page = rows[:limit]
        has_next = len(rows) > limit

        requests: list[ChatJoinRequestDTO] = []
        for request, profile in page:
            dto = ChatJoinRequestDTO.model_validate(request)
            dto.profile = (
                ChatProfileDTO.model_validate(profile)
                if profile is not None
                else ChatProfileDTO(user_id=request.user_id)
            )
            requests.append(dto)

        profiles = [dto.profile for dto in requests]
        await self.privacy_service.hide_avatars(user_id, profiles)
        await self.message_service.image_urls(profiles)

        last = page[-1][0] if has_next and page else None
        return ListJoinRequests(
            requests=requests,
            total=await self.join_request_repository.count_pending(query.chat_id),
            has_next=has_next,
            next_requested_at=last.requested_at if last is not None else None,
            next_user_id=last.user_id if last is not None else None,
        )
