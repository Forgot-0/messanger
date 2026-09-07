from unittest.mock import AsyncMock, MagicMock

import orjson
import pytest
from fastapi.websockets import WebSocketState

from app.core.configs.app import app_config
from app.core.websocket.websocket import WSConnection


def make_ws_mock() -> MagicMock:
    ws = MagicMock()
    ws.application_state = MagicMock()
    ws.application_state.__eq__ = lambda self, other: True  # CONNECTED
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    ws.receive = AsyncMock(return_value={"type": "websocket.disconnect"})
    return ws


def make_connection(user_id: int = 1) -> WSConnection:
    ws = make_ws_mock()
    ws.application_state = WebSocketState.CONNECTED
    return WSConnection(
        websocket=ws,
        user_id=user_id,
        device_id="test-device",
        gateway_id="test-gateway",
    )


@pytest.mark.unit
@pytest.mark.chats
class TestTrySend:

    def test_try_send_returns_true_on_success(self) -> None:
        conn = make_connection()
        result = conn.try_send({"type": "ws.ping", "payload": {}})

        assert result is True

    def test_try_send_puts_message_into_queue(self) -> None:
        conn = make_connection()
        conn.try_send({"type": "ws.pong", "payload": {}})

        assert conn.send_queue.qsize() == 1

    def test_try_send_returns_false_when_closed(self) -> None:
        conn = make_connection()
        conn.closed = True
        result = conn.try_send({"type": "ws.ping", "payload": {}})

        assert result is False
        assert conn.send_queue.qsize() == 0

    def test_try_send_returns_false_when_queue_full(self) -> None:
        conn = make_connection()

        for i in range(app_config.WS_SEND_QUEUE_SIZE):
            conn.try_send({"type": "ws.msg", "seq": i})

        result = conn.try_send({"type": "ws.overflow", "payload": {}})
        assert result is False

    def test_try_send_multiple_messages_queued_in_order(self) -> None:
        conn = make_connection()
        messages = [{"type": "ws.msg", "seq": i} for i in range(3)]

        for msg in messages:
            conn.try_send(msg)

        assert conn.send_queue.qsize() == 3

        for expected in messages:
            raw = conn.send_queue.get_nowait()
            assert orjson.loads(raw) == expected

    def test_try_send_does_not_raise_on_any_dict(self) -> None:
        conn = make_connection()
        conn.try_send({})
        conn.try_send({"nested": {"key": [1, 2, 3]}})
        conn.try_send({"type": None})

        assert conn.send_queue.qsize() == 3


@pytest.mark.unit
@pytest.mark.chats
class TestTouch:

    def test_touch_updates_last_seen_at(self) -> None:
        conn = make_connection()
        before = conn.last_seen_at
        conn.touch()

        assert conn.last_seen_at >= before

    def test_touch_does_not_affect_connected_at(self) -> None:
        conn = make_connection()
        connected_at = conn.connected_at
        conn.touch()

        assert conn.connected_at == connected_at


@pytest.mark.unit
@pytest.mark.chats
class TestClosedBehavior:

    def test_initial_closed_is_false(self) -> None:
        conn = make_connection()
        assert conn.closed is False

    def test_try_send_after_closed_is_noop(self) -> None:
        conn = make_connection()
        conn.closed = True

        result = conn.try_send({"type": "ws.test"})

        assert result is False
        assert conn.send_queue.empty()

    def test_multiple_sends_after_close_all_return_false(self) -> None:
        conn = make_connection()
        conn.closed = True
        results = [conn.try_send({"type": f"msg-{i}"}) for i in range(5)]

        assert all(r is False for r in results)

    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        conn = make_connection()

        await conn.close(code=1000, reason="test")
        assert conn.closed is True

        await conn.close(code=1000, reason="again")
        assert conn.closed is True


@pytest.mark.unit
@pytest.mark.chats
class TestSubscriptions:

    def test_initial_subscriptions_empty(self) -> None:
        conn = make_connection()
        assert len(conn.subscriptions) == 0

    def test_last_seq_by_chat_initially_empty(self) -> None:
        conn = make_connection()
        assert len(conn.last_seq_by_chat) == 0

    def test_can_add_to_subscriptions(self) -> None:
        conn = make_connection()
        conn.subscriptions.add("chat-abc")

        assert "chat-abc" in conn.subscriptions

    def test_subscriptions_is_a_set(self) -> None:
        conn = make_connection()
        conn.subscriptions.add("chat-1")
        conn.subscriptions.add("chat-1")

        assert len(conn.subscriptions) == 1


@pytest.mark.unit
@pytest.mark.chats
class TestQueueConfig:

    def test_queue_max_size_matches_config(self) -> None:
        conn = make_connection()
        assert conn.send_queue.maxsize == app_config.WS_SEND_QUEUE_SIZE

    def test_queue_accepts_exactly_max_items(self) -> None:
        conn = make_connection()

        for i in range(app_config.WS_SEND_QUEUE_SIZE):
            result = conn.try_send({"seq": i})
            assert result is True

        overflow = conn.try_send({"seq": "overflow"})
        assert overflow is False
