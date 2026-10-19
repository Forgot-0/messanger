import logging
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.join_requests import JoinRequestsResolutionDTO
from app.chats.exceptions import AccessDeniedChatError, MemberLimitExceededError
from app.chats.models.chat import Chat
from app.chats.models.join_request import ChatJoinRequest
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.invite import ChatInviteLinkRepository
from app.chats.repositories.join_request import ChatJoinRequestRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ApproveJoinRequestsCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    user_ids: list[int]


@dataclass(frozen=True)
class ApproveJoinRequestsCommandHandler(
    BaseCommandHandler[ApproveJoinRequestsCommand, JoinRequestsResolutionDTO]
):
    session: AsyncSession
    chat_repository: ChatRepository
    join_request_repository: ChatJoinRequestRepository
    invite_repository: ChatInviteLinkRepository
    access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: ApproveJoinRequestsCommand) -> JoinRequestsResolutionDTO:
        requester_id = int(command.user_jwt_data.id)
        wanted = list(dict.fromkeys(int(user_id) for user_id in command.user_ids))

        chat, requester = await self.chat_repository.get_chat_and_member(
            chat_id=command.chat_id, member_id=requester_id
        )
        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=requester,
            must_permissions={"member:invite"},
        ):
            raise AccessDeniedChatError(chat_id=str(chat.id), requester_id=requester_id)

        pending = await self.join_request_repository.list_pending_for(
            chat.id, wanted, with_for_update=True
        )
        members = await self.chat_repository.members_by_user_ids(
            chat.id, [request.user_id for request in pending]
        )

        approved: list[int] = []
        skipped = set(wanted)
        to_add: list[ChatJoinRequest] = []

        for request in pending:
            member = members.get(request.user_id)
            if member is not None and member.is_banned:
                continue

            request.approve(resolved_by=requester_id)
            approved.append(request.user_id)
            skipped.discard(request.user_id)

            if member is None:
                to_add.append(request)

        role_id = Chat.default_member_role(chat.type)
        if to_add:
            limit = Chat.member_limit(chat.type)
            if (
                await self.chat_repository.shift_member_count(
                    chat.id, delta=len(to_add), limit=limit
                )
                is None
            ):
                raise MemberLimitExceededError(limit=limit)

            for request in to_add:
                chat.add_member(request.user_id, role_id=role_id)

            await self.invite_repository.credit_usage(
                Counter(
                    request.invite_link_id
                    for request in to_add
                    if request.invite_link_id is not None
                )
            )

        chat.approve_join_requests(approved, resolved_by=requester_id, role_id=role_id)

        await self.event_bus.publish(chat.pull_events())
        await self.session.commit()

        logger.info(
            "Join requests approved",
            extra={
                "chat_id": str(command.chat_id),
                "approved": len(approved),
                "skipped": len(skipped),
                "by": requester_id,
            },
        )
        return JoinRequestsResolutionDTO(resolved=approved, skipped=sorted(skipped))
