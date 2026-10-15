from dataclasses import dataclass

from app.chats.dtos.chats import ChatPreviewDTO
from app.chats.dtos.invites import ChatInvitePreviewDTO
from app.chats.exceptions import InviteLinkExpiredError, NotFoundInviteLinkError
from app.chats.models.chat import ChatType
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.invite import ChatInviteLinkRepository
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

        member_of = await self.chat_repository.member_chat_ids(
            int(query.user_jwt_data.id), [chat.id]
        )

        preview = ChatPreviewDTO.model_validate(chat)
        preview.is_member = chat.id in member_of
        return ChatInvitePreviewDTO(chat=preview, expires_at=invite.expires_at)
