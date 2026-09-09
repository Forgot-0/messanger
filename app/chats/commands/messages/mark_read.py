import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.exceptions import AccessDeniedChatError
from app.chats.repositories.chat import ChatRepository
from app.chats.repositories.reads import ReadReceiptRepository
from app.chats.services.access import ChatAccessService
from app.chats.services.read_coalescer import ReadReceiptCoalesceQueue
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.events.service import BaseEventBus
from app.core.services.auth.dto import UserJWTData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarkAsReadCommand(BaseCommand):
    chat_id: UUID
    message_seq: int

    user_jwt_data: UserJWTData


@dataclass(frozen=True)
class MarkAsReadCommandHandler(BaseCommandHandler[MarkAsReadCommand, None]):
    session: AsyncSession
    chat_repository: ChatRepository
    access_service: ChatAccessService
    read_receipt_repository: ReadReceiptRepository
    coalesce_queue: ReadReceiptCoalesceQueue
    event_bus: BaseEventBus

    async def handle(self, command: MarkAsReadCommand) -> None:
        user_id = int(command.user_jwt_data.id)

        chat, member = await self.chat_repository.get_chat_and_member(
            chat_id=command.chat_id, member_id=user_id
        )

        if not await self.access_service.has_permissions(
            user_jwt_data=command.user_jwt_data,
            member=member,
            must_permissions={"message:read"}
        ):
            raise AccessDeniedChatError(chat_id=str(command.chat_id), requester_id=user_id)

        message_seq = min(command.message_seq, chat.seq_counter)
        support_read_event = chat.support_read_event

        await self.coalesce_queue.enqueue(
            chat_id=command.chat_id,
            user_id=user_id,
            message_seq=message_seq,
            support_read_event=support_read_event,
        )

