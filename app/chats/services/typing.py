from dataclasses import dataclass

from app.chats.config import chat_config
from app.chats.models.chat import ChatFanoutStrategy
from app.chats.schemas.ws import TypingAction


@dataclass(slots=True)
class TypingContext:
    fanout_strategy: ChatFanoutStrategy
    denied_code: str | None
    loaded_at: float

    def is_fresh(self, now: float) -> bool:
        return now - self.loaded_at < chat_config.TYPING_CONTEXT_TTL_SECONDS


@dataclass(slots=True)
class TypingState:
    context: TypingContext | None = None
    action: TypingAction | None = None
    sent_at: float = 0.0

    def is_active(self, now: float) -> bool:
        return self.action is not None and now - self.sent_at < chat_config.TYPING_TTL_SECONDS

    def is_throttled(self, action: TypingAction, now: float) -> bool:
        return (
            self.action == action
            and (now - self.sent_at) * 1000 < chat_config.TYPING_BROADCAST_INTERVAL_MS
        )


def track_typing_state(states: dict[str, TypingState], chat_id: str, now: float) -> TypingState:
    state = states.get(chat_id)
    if state is not None:
        return state

    if len(states) >= chat_config.TYPING_MAX_TRACKED_CHATS:
        for stale in [key for key, item in states.items() if not item.is_active(now)]:
            del states[stale]

    if len(states) >= chat_config.TYPING_MAX_TRACKED_CHATS:
        del states[min(states, key=lambda key: states[key].sent_at)]

    state = TypingState()
    states[chat_id] = state
    return state
