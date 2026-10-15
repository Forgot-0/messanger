import pytest

from app.chats.config import chat_config
from app.chats.models.chat import ChatFanoutStrategy
from app.chats.schemas.ws import TypingAction
from app.chats.services.typing import TypingContext, TypingState, track_typing_state

INTERVAL = chat_config.TYPING_BROADCAST_INTERVAL_MS / 1000


@pytest.mark.unit
@pytest.mark.chats
class TestTypingState:

    def test_same_action_is_throttled_inside_the_interval(self) -> None:
        state = TypingState(action=TypingAction.TYPING, sent_at=100.0)

        assert state.is_throttled(TypingAction.TYPING, 100.0 + INTERVAL / 2)
        assert not state.is_throttled(TypingAction.TYPING, 100.0 + INTERVAL)

    def test_switching_action_is_never_throttled(self) -> None:
        state = TypingState(action=TypingAction.TYPING, sent_at=100.0)

        assert not state.is_throttled(TypingAction.UPLOAD_PHOTO, 100.1)

    def test_active_only_while_the_receiver_still_shows_it(self) -> None:
        state = TypingState(action=TypingAction.RECORD_VOICE, sent_at=50.0)

        assert state.is_active(50.0 + chat_config.TYPING_TTL_SECONDS - 0.1)
        assert not state.is_active(50.0 + chat_config.TYPING_TTL_SECONDS)
        assert not TypingState().is_active(50.0)

    def test_context_expires(self) -> None:
        context = TypingContext(ChatFanoutStrategy.FANOUT_ON_WRITE, None, loaded_at=10.0)

        assert context.is_fresh(10.0 + chat_config.TYPING_CONTEXT_TTL_SECONDS - 1)
        assert not context.is_fresh(10.0 + chat_config.TYPING_CONTEXT_TTL_SECONDS)


@pytest.mark.unit
@pytest.mark.chats
class TestTrackTypingState:

    def test_returns_the_same_state_for_the_same_chat(self) -> None:
        states: dict[str, TypingState] = {}

        first = track_typing_state(states, "chat-a", now=1.0)
        first.action = TypingAction.TYPING

        assert track_typing_state(states, "chat-a", now=2.0) is first

    def test_bounded_by_dropping_idle_chats_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(chat_config, "TYPING_MAX_TRACKED_CHATS", 3)
        now = 1_000.0
        states = {
            "idle-1": TypingState(action=None, sent_at=now - 1),
            "idle-2": TypingState(action=TypingAction.TYPING, sent_at=now - 600),
            "busy": TypingState(action=TypingAction.TYPING, sent_at=now - 1),
        }

        track_typing_state(states, "new", now=now)

        assert set(states) == {"busy", "new"}

    def test_evicts_the_oldest_when_everything_is_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(chat_config, "TYPING_MAX_TRACKED_CHATS", 2)
        now = 1_000.0
        states = {
            "older": TypingState(action=TypingAction.TYPING, sent_at=now - 2),
            "newer": TypingState(action=TypingAction.TYPING, sent_at=now - 1),
        }

        track_typing_state(states, "new", now=now)

        assert set(states) == {"newer", "new"}
