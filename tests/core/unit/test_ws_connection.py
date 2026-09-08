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

    def test_try_send_queues_messages_in_order_and_stamps_them(self) -> None:
        conn = make_connection()

        for i in range(3):
            assert conn.try_send({"type": "ws.msg", "seq": i}) is True

        assert conn.send_queue.qsize() == 3

        for expected_seq in range(3):
            queued = orjson.loads(conn.send_queue.get_nowait())
            assert queued["type"] == "ws.msg"
            assert queued["seq"] == expected_seq
            assert queued["enqueued_at"]

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


@pytest.mark.unit
@pytest.mark.chats
class TestQueueConfig:

    def test_queue_max_size_matches_config(self) -> None:
        conn = make_connection()
        assert conn.send_queue.maxsize == app_config.WS_SEND_QUEUE_SIZE
