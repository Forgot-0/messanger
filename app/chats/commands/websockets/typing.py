import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid7

from app.chats.config import chat_config
from app.chats.dtos.delivery import WsEvent
from app.chats.exceptions import (
    MessagesPrivacyRestrictedError,
    NotFoundChatError,
    UserBlockedError,
)
from app.chats.models.chat import ChatFanoutStrategy, ChatType
from app.chats.repositories.chat import ChatRepository
from app.chats.schemas.ws import TypingAction, WSClientOp, WSEventType
from app.chats.services.access import ChatAccessService
from app.chats.services.delivery_router import ChatDeliveryRouter
from app.chats.services.privacy import ChatPrivacyService
from app.chats.services.typing import TypingContext, TypingState, track_typing_state
from app.core.commands import BaseCommand, BaseCommandHandler
from app.core.utils import now_utc
from app.core.websocket.websocket import WSConnection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TypingCommand(BaseCommand):
    conn: WSConnection
    chat_id: UUID
    action: TypingAction = TypingAction.TYPING
    op: WSClientOp = WSClientOp.TYPING


@dataclass(frozen=True)
class TypingCommandHandler(BaseCommandHandler[TypingCommand, None]):
    chat_repository: ChatRepository
    access_service: ChatAccessService
    privacy_service: ChatPrivacyService
    delivery_router: ChatDeliveryRouter

    async def handle(self, command: TypingCommand) -> None:
        now = time.monotonic()
        states: dict[str, TypingState] = command.conn.typing_by_chat

        if command.action == TypingAction.CANCEL:
            state = states.get(str(command.chat_id))
            if state is None or state.context is None or not state.is_active(now):
                return

            state.action = None
            await self.send(
                command.chat_id,
                state.context.fanout_strategy,
                WSEventType.TYPING_STOP,
                {"user_id": command.conn.user_id}
            )
            return

        state = track_typing_state(states, str(command.chat_id), now)
        if state.is_throttled(command.action, now):
            return

        context = state.context
        if context is None or not context.is_fresh(now):
            context = await self.typing_context(command.conn.user_id, command.chat_id, now)
            state.context = context

            if context.denied_code is not None:
                command.conn.try_send({
                    "type": "ws.error",
                    "code": context.denied_code,
                    "detail": "BAD COMMAND",
                })

        if context.denied_code is not None:
            return

        state.action = command.action
        state.sent_at = now
        await self.send(
            command.chat_id,
            context.fanout_strategy,
            WSEventType.TYPING_START,
            {
                "user_id": command.conn.user_id,
                "action": command.action.value,
                "expires_in": chat_config.TYPING_TTL_SECONDS,
            },
        )

    async def typing_context(self, user_id: int, chat_id: UUID, now: float) -> TypingContext:
        try:
            chat, member = await self.chat_repository.get_chat_and_member(
                chat_id=chat_id, member_id=user_id
            )
        except NotFoundChatError:
            return TypingContext(ChatFanoutStrategy.FANOUT_ON_WRITE, "NOT_FOUND_CHAT", now)

        if member.is_banned:
            return TypingContext(chat.fanout_strategy, "NOT_CHAT_MEMBER", now)

        if chat.type == ChatType.CHANNEL or not self.access_service.member_can_send(chat, member):
            return TypingContext(chat.fanout_strategy, "CHAT_ACCESS_DENIED", now)

        try:
            await self.privacy_service.ensure_can_message(chat, user_id)
        except UserBlockedError:
            return TypingContext(chat.fanout_strategy, "USER_BLOCKED", now)
        except MessagesPrivacyRestrictedError:
            return TypingContext(chat.fanout_strategy, "MESSAGES_PRIVACY_RESTRICTED", now)

        return TypingContext(chat.fanout_strategy, None, now)

    async def send(
        self,
        chat_id: UUID,
        fanout_strategy: ChatFanoutStrategy,
        ws_type: WSEventType,
        delta: dict[str, Any],
    ) -> None:
        ts = now_utc()
        await self.delivery_router.route_ephemeral(
            WsEvent(
                type=ws_type.value,
                event_name=ws_type.value,
                event_id=str(uuid7()),
                chat_id=chat_id,
                delta=delta,
                ts=ts.isoformat(),
                fanout_strategy=fanout_strategy,
            ),
            expires_at=(ts + timedelta(seconds=chat_config.TYPING_TTL_SECONDS)).isoformat(),
            exclude_user_ids=frozenset({delta["user_id"]}),
        )
