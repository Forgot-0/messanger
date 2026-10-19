import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import (
    AccessDeniedChatError,
    JoinRequestNotPendingError,
    NotFoundJoinRequestError,
)
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.join_request import ChatJoinRequestRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeclineJoinRequestCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID
    target_user_id: int


@dataclass(frozen=True)
class DeclineJoinRequestCommandHandler(BaseCommandHandler[DeclineJoinRequestCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    join_request_repository: ChatJoinRequestRepository
    access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(self, command: DeclineJoinRequestCommand) -> None:
        requester_id = int(command.user_jwt_data.id)

        member = await self.chat_repository.get_member_chat(command.chat_id, requester_id)
        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=member,
            must_permissions={"member:invite"},
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=requester_id)

        request = await self.join_request_repository.get(
            command.chat_id, command.target_user_id, with_for_update=True
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

        request.decline(resolved_by=requester_id)

        await self.event_bus.publish(request.pull_events())
        await self.session.commit()

        logger.info(
            "Join request declined",
            extra={
                "chat_id": str(command.chat_id),
                "user_id": command.target_user_id,
                "by": requester_id,
            },
        )
