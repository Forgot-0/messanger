import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import NotFoundJoinRequestError
from app.chats.repositories.join_request import ChatJoinRequestRepository
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CancelJoinRequestCommand(BaseCommand):
    user_jwt_data: UserJWTData
    chat_id: UUID


@dataclass(frozen=True)
class CancelJoinRequestCommandHandler(BaseCommandHandler[CancelJoinRequestCommand, None]):
    session: AsyncSession
    join_request_repository: ChatJoinRequestRepository
    event_bus: BaseEventBus

    async def handle(self, command: CancelJoinRequestCommand) -> None:
        user_id = int(command.user_jwt_data.id)

        request = await self.join_request_repository.get(command.chat_id, user_id)
        if request is None or not request.is_pending:
            raise NotFoundJoinRequestError(chat_id=str(command.chat_id), user_id=user_id)

        request.cancel()
        await self.join_request_repository.delete(request)

        await self.event_bus.publish(request.pull_events())
        await self.session.commit()

        logger.info(
            "Join request cancelled",
            extra={"chat_id": str(command.chat_id), "user_id": user_id},
        )
