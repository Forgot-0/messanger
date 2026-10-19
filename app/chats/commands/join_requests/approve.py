import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import (
    AccessDeniedChatError,
    JoinRequestNotPendingError,
    MemberLimitExceededError,
    NotFoundJoinRequestError,
)
from app.chats.models.chat import Chat
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.invite import ChatInviteLinkRepository
from app.chats.repositories.join_request import ChatJoinRequestRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApproveJoinRequestCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    target_user_id: int


@dataclass(frozen=True)
class ApproveJoinRequestCommandHandler(BaseCommandHandler[ApproveJoinRequestCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    join_request_repository: ChatJoinRequestRepository
    invite_repository: ChatInviteLinkRepository
    access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: ApproveJoinRequestCommand) -> None:
        requester_id = int(command.user_jwt_data.id)

        chat, requester = await self.chat_repository.get_chat_and_member(
            chat_id=command.chat_id, member_id=requester_id
        )
        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=requester,
            must_permissions={"member:invite"},
        ):
            raise AccessDeniedChatError(chat_id=str(chat.id), requester_id=requester_id)

        request = await self.join_request_repository.get(
            chat.id, command.target_user_id, with_for_update=True
        )
        if request is None:
            raise NotFoundJoinRequestError(
                chat_id=str(command.chat_id), user_id=command.target_user_id
            )

        if not request.is_pending:
            raise JoinRequestNotPendingError(
                chat_id=str(command.chat_id),
                user_id=command.target_user_id,
                status_value=request.status.value,
            )

        existing = await self.chat_repository.get_member_chat(
            chat.id, command.target_user_id, with_role=False
        )
        if existing is not None:
            if existing.is_banned:
                raise AccessDeniedChatError(
                    chat_id=str(chat.id), requester_id=command.target_user_id
                )

            request.approve(resolved_by=requester_id, role_id=existing.role_id)
            await self.event_bus.publish(request.pull_events())
            await self.session.commit()
            return

        role_id = Chat.default_member_role(chat.type)
        limit = Chat.member_limit(chat.type)
        if await self.chat_repository.shift_member_count(chat.id, delta=1, limit=limit) is None:
            raise MemberLimitExceededError(limit=limit)

        chat.add_member(command.target_user_id, role_id=role_id)
        request.approve(resolved_by=requester_id, role_id=role_id)

        if request.invite_link_id is not None:
            await self.invite_repository.consume(request.invite_link_id)

        await self.event_bus.publish([*chat.pull_events(), *request.pull_events()])
        await self.session.commit()

        logger.info(
            "Join request approved",
            extra={
                "chat_id": str(command.chat_id),
                "user_id": command.target_user_id,
                "by": requester_id,
            },
        )
