import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

import orjson
from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.core.configs.app import app_config
from app.core.metrics import EVICTION_REASON_HEARTBEAT_TIMEOUT, WS_CONNECTION_EVICTIONS
from app.core.utils import now_utc


@dataclass(slots=True)
class WSConnection:
    websocket: WebSocket
    user_id: int
    device_id: str
    gateway_id: str
    connection_id: str = field(default_factory=lambda: str(uuid4()))
    connected_at: datetime = field(default_factory=now_utc)
    last_seen_at: datetime = field(default_factory=now_utc)
    subscriptions: set[str] = field(default_factory=set)
    last_seq_by_chat: dict[str, int] = field(default_factory=dict)
    send_queue: asyncio.Queue[bytes] = field(
        default_factory=lambda: asyncio.Queue(maxsize=app_config.WS_SEND_QUEUE_SIZE)
    )
    writer_task: asyncio.Task[None] | None = field(default=None)
    heartbeat_task: asyncio.Task[None] | None = field(default=None)
    closed: bool = field(default=False)

    async def start(self) -> None:
        await self._start_writer()
        await self._start_heartbeat()

    async def _start_writer(self) -> None:
        if self.writer_task and not self.writer_task.done():
            return

        self.writer_task = asyncio.create_task(
            self._writer_loop(), name=f"ws:writer:{self.connection_id}"
        )

    async def _start_heartbeat(self) -> None:
        if self.heartbeat_task and not self.heartbeat_task.done():
            return

        self.heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name=f"ws:heartbeat:{self.connection_id}"
        )

    async def _writer_loop(self) -> None:
        try:
            while (
                not self.closed
                and self.websocket.application_state == WebSocketState.CONNECTED
            ):
                try:
                    payload = await asyncio.wait_for(
                        self.send_queue.get(), timeout=5.0
                    )
                except TimeoutError:
                    continue

                await self.websocket.send_text(payload.decode())
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                await self.close(code=1011, reason="writer error")

    async def _heartbeat_loop(self) -> None:
        try:
            while (
                not self.closed
                and self.websocket.application_state == WebSocketState.CONNECTED
            ):
                await asyncio.sleep(app_config.WS_HEARTBEAT_INTERVAL)
                if self.closed:
                    return

                idle = (now_utc() - self.last_seen_at).total_seconds()

                if idle > app_config.WS_HEARTBEAT_TIMEOUT:
                    WS_CONNECTION_EVICTIONS.labels(
                        gateway_id=self.gateway_id,
                        reason=EVICTION_REASON_HEARTBEAT_TIMEOUT,
                    ).inc()
                    await self.close(code=1001, reason="heartbeat timeout")
                    return

                if not self.try_send(
                    {
                        "type": "ws.ping",
                        "connection_id": self.connection_id,
                    }
                ):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    def touch(self) -> None:
        self.last_seen_at = now_utc()

    def try_send(self, event: dict[str, Any]) -> bool:

        if self.closed:
            return False

        event["enqueued_at"] = now_utc().isoformat()

        try:
            self.send_queue.put_nowait(orjson.dumps(event))
        except asyncio.QueueFull:
            return False
        else:
            return True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return

        self.closed = True

        current = asyncio.current_task()
        for task in (self.writer_task, self.heartbeat_task):
            if task and task is not current and not task.done():
                task.cancel()

        if self.websocket.application_state == WebSocketState.CONNECTED:
            with contextlib.suppress(RuntimeError, Exception):
                await self.websocket.close(code=code, reason=reason[:120])

        for task in (self.writer_task, self.heartbeat_task):
            if task and task is not current:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
