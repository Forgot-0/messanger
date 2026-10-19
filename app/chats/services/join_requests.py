from dataclasses import dataclass
from uuid import UUID

from app.chats.config import chat_config
from app.chats.exceptions import (
    AccessDeniedChatError,
    AlreadyMemberError,
    JoinRequestsLimitExceededError,
)
from app.chats.models.chat import Chat
from app.chats.models.join_request import ChatJoinRequest
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.join_request import ChatJoinRequestRepository


@dataclass
class ChatJoinRequestService:
    chat_repository: ChatRepository
    join_request_repository: ChatJoinRequestRepository

    async def submit(
        self,
        chat: Chat,
        user_id: int,
        invite_link_id: UUID | None = None,
    ) -> ChatJoinRequest:
        member = await self.chat_repository.get_member_chat(chat.id, user_id, with_role=False)
        if member is not None:
            if member.is_banned:
                raise AccessDeniedChatError(chat_id=str(chat.id), requester_id=user_id)
            raise AlreadyMemberError(user_id=user_id, chat_id=str(chat.id))

        if (
            await self.join_request_repository.count_pending(chat.id)
            >= chat_config.MAX_PENDING_JOIN_REQUESTS
        ):
            raise JoinRequestsLimitExceededError(chat_id=str(chat.id))

        existing = await self.join_request_repository.get(chat.id, user_id)
        if existing is not None:
            existing.renew(invite_link_id=invite_link_id)
            return existing

        request = ChatJoinRequest.create(
            chat_id=chat.id, user_id=user_id, invite_link_id=invite_link_id
        )
        await self.join_request_repository.create(request)
        return request
