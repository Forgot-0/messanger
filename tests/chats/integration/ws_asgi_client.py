import asyncio
import contextlib
from typing import Any
from urllib.parse import urlencode

import orjson
from fastapi import FastAPI
from starlette.types import Message, Scope


class WebSocketDenied(Exception):
    def __init__(self, close_message: Message) -> None:
        self.close_message = close_message
        code = close_message.get("code")
        self.code = int(code) if code is not None else 1000
        super().__init__(close_message)


def _ws_scope(
    app: FastAPI,
    *,
    path: str,
    query: dict[str, str] | None,
    headers: list[tuple[bytes, bytes]],
    subprotocols: list[str],
) -> Scope:
    path_only = path.split("?", 1)[0]
    qs = (
        path.split("?", 1)[1].encode("latin-1")
        if "?" in path
        else urlencode(query or {}).encode("latin-1")
    )
    state = dict(app.state._state)
    return {
        "type": "websocket",
        "path": path_only,
        "raw_path": path_only.encode("utf-8"),
        "root_path": "",
        "scheme": "ws",
        "query_string": qs,
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("test", 80),
        "subprotocols": subprotocols,
        "state": state,
        "extensions": {"websocket.http.response": {}},
    }


class AsyncASGIWebSocketSession:
    def __init__(
        self,
        app: FastAPI,
        *,
        path: str,
        query: dict[str, str] | None = None,
        headers: list[tuple[bytes, bytes]] | None = None,
        subprotocols: list[str] | None = None,
    ) -> None:
        self.app = app
        self._to_app: asyncio.Queue[Message] = asyncio.Queue()
        self._from_app: asyncio.Queue[Message] = asyncio.Queue()
        base_headers = [(b"host", b"test")]
        merged = [
            *base_headers, *(headers or []),
            (b"sec-websocket-protocol", ",".join(subprotocols or []).encode())
        ]
        self.scope = _ws_scope(
            app,
            path=path,
            query=query,
            headers=merged,
            subprotocols=subprotocols or [],
        )
        self._task: asyncio.Task[None] | None = None
        self._accepted_subprotocol: str | None = None
        self._accepted = False
        self._deny_close: Message | None = None

    async def __aenter__(self) -> AsyncASGIWebSocketSession:
        async def receive() -> Message:
            return await self._to_app.get()

        async def send(message: Message) -> None:
            await self._from_app.put(message)

        await self._to_app.put({"type": "websocket.connect"})
        self._task = asyncio.create_task(self.app(self.scope, receive, send))
        accepted = await self._drain_until_accept()
        if not accepted:
            close_msg = self._deny_close or {"type": "websocket.close", "code": 1008, "reason": ""}
            if self._task:
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._task
                self._task = None
            raise WebSocketDenied(close_msg)
        self._accepted = True
        return self

    async def __aexit__(self, *args: object) -> None:
        if not self._accepted:
            return
        with contextlib.suppress(Exception):
            await self._to_app.put({"type": "websocket.disconnect", "code": 1000, "reason": ""})
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def _drain_until_accept(self) -> bool:
        while True:
            msg = await self._from_app.get()
            t = msg["type"]
            if t == "websocket.accept":
                self._accepted_subprotocol = msg.get("subprotocol")
                return True
            if t == "websocket.close":
                self._deny_close = msg
                return False
            if t == "websocket.http.response.start":
                raise RuntimeError("websocket denied via HTTP response")
            if t == "websocket.send":
                continue
            raise RuntimeError(f"unexpected ASGI message before accept: {msg!r}")

    async def recv_event(self, *, timeout: float = 10.0) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for websocket.send from app")
            msg = await asyncio.wait_for(self._from_app.get(), timeout=remaining)
            if msg["type"] == "websocket.send":
                if "text" in msg:
                    raw = msg["text"]
                    data = orjson.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
                    if isinstance(data, dict):
                        return data
                elif "bytes" in msg:
                    data = orjson.loads(msg["bytes"])
                    if isinstance(data, dict):
                        return data
            if msg["type"] == "websocket.close":
                raise RuntimeError(f"server closed: {msg}")

    async def send_json(self, payload: dict[str, Any]) -> None:
        body = orjson.dumps(payload).decode("utf-8")
        await self._to_app.put({"type": "websocket.receive", "text": body})

    async def send_raw_text(self, text: str) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": text})

    async def send_bytes(self, data: bytes) -> None:
        await self._to_app.put({"type": "websocket.receive", "bytes": data})

    @property
    def accepted_subprotocol(self) -> str | None:
        return self._accepted_subprotocol


async def recv_until_type(
    ws: AsyncASGIWebSocketSession,
    event_type: str,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"no event type {event_type!r}")
        ev = await ws.recv_event(timeout=remaining)
        if ev.get("type") == event_type:
            return ev
