import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.dtos.join_requests import JoinRequestsDismissedDTO
from app.chats.exceptions import AccessDeniedChatError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.join_request import ChatJoinRequestRepository
from app.chats.services.access import ChatAccessService
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class DeclineAllJoinRequestsCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID


@dataclass(frozen=True)
class DeclineAllJoinRequestsCommandHandler(
    BaseCommandHandler[DeclineAllJoinRequestsCommand, JoinRequestsDismissedDTO]
):
    session: AsyncSession
    chat_repository: ChatRepository
    join_request_repository: ChatJoinRequestRepository
    access_service: ChatAccessService
    event_bus: BaseEventBus

    async def handle(
        self, command: DeclineAllJoinRequestsCommand
    ) -> JoinRequestsDismissedDTO:
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

        declined = await self.join_request_repository.decline_all(
            chat.id, resolved_by=requester_id
        )
        if declined:
            chat.decline_join_requests(
                [], resolved_by=requester_id, count=declined, decline_all=True
            )
            await self.event_bus.publish(chat.pull_events())

        await self.session.commit()

        logger.info(
            "All join requests declined",
            extra={"chat_id": str(command.chat_id), "declined": declined, "by": requester_id},
        )
        return JoinRequestsDismissedDTO(declined=declined)
