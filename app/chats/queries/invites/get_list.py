from dataclasses import dataclass
from uuid import UUID

from app.chats.config import chat_config
from app.chats.dtos.invites import ChatInviteLinkDTO, ListInviteLinks
from app.chats.exceptions import AccessDeniedChatError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.invite import ChatInviteLinkRepository
from app.chats.services.access import ChatAccessService
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData


@dataclass(frozen=True, kw_only=True)
class GetInviteLinksQuery(BaseQuery):
    user_jwt_data: UserJWTData
    chat_id: UUID
    limit: int = chat_config.INVITE_LINKS_PAGE_SIZE
    last_invite_id: UUID | None = None


@dataclass(frozen=True)
class GetInviteLinksQueryHandler(BaseQueryHandler[GetInviteLinksQuery, ListInviteLinks]):
    chat_repository: ChatRepository
    invite_repository: ChatInviteLinkRepository
    access_service: ChatAccessService

    async def handle(self, query: GetInviteLinksQuery) -> ListInviteLinks:
        user_id = int(query.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(query.chat_id, user_id)
        if not await self.access_service.has_permissions(
            user_jwt_data=query.user_jwt_data,
            member=member,
            must_permissions={"member:invite"},
        ):
            raise AccessDeniedChatError(chat_id=str(query.chat_id), requester_id=user_id)

        limit = min(max(query.limit, 1), chat_config.INVITE_LINKS_MAX_PAGE_SIZE)
        rows = await self.invite_repository.list_page(
            chat_id=query.chat_id,
            limit=limit,
            last_invite_id=query.last_invite_id,
        )
        page = rows[:limit]
        has_next = len(rows) > limit

        return ListInviteLinks(
            invites=[ChatInviteLinkDTO.model_validate(invite) for invite in page],
            has_next=has_next,
            next_invite_id=page[-1].id if has_next and page else None,
        )
