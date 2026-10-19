from dataclasses import dataclass

from app.chats.dtos.chats import ChatPreviewDTO
from app.chats.dtos.invites import ChatInvitePreviewDTO
from app.chats.exceptions import InviteLinkExpiredError, NotFoundInviteLinkError
from app.chats.models.chat import ChatType
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.invite import ChatInviteLinkRepository
from app.chats.repositories.join_request import ChatJoinRequestRepository
from app.core.queries import BaseQuery, BaseQueryHandler
from app.core.services.auth.dto import UserJWTData


@dataclass(frozen=True, kw_only=True)
class GetInvitePreviewQuery(BaseQuery):
    user_jwt_data: UserJWTData
    code: str


@dataclass(frozen=True)
class GetInvitePreviewQueryHandler(BaseQueryHandler[GetInvitePreviewQuery, ChatInvitePreviewDTO]):
    chat_repository: ChatRepository
    invite_repository: ChatInviteLinkRepository
    join_request_repository: ChatJoinRequestRepository

    async def handle(self, query: GetInvitePreviewQuery) -> ChatInvitePreviewDTO:
        invite = await self.invite_repository.get_by_code(query.code)
        if invite is None:
            raise NotFoundInviteLinkError(invite=query.code)

        reason = invite.inactive_reason
        if reason is not None:
            raise InviteLinkExpiredError(reason=reason)

        chat = await self.chat_repository.get_by_id(invite.chat_id)
        if chat is None or chat.type == ChatType.DIRECT:
            raise NotFoundInviteLinkError(invite=query.code)

        user_id = int(query.user_jwt_data.id)
        member_of = await self.chat_repository.member_chat_ids(user_id, [chat.id])

        preview = ChatPreviewDTO.model_validate(chat)
        preview.is_member = chat.id in member_of

        join_request = None
        if invite.creates_join_request and not preview.is_member:
            join_request = await self.join_request_repository.get(chat.id, user_id)

        return ChatInvitePreviewDTO(
            chat=preview,
            expires_at=invite.expires_at,
            creates_join_request=invite.creates_join_request,
            join_request_status=join_request.status if join_request is not None else None,
        )
