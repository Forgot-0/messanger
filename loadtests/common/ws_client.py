"""
Тонкая обёртка над websocket-client (синхронная, кооперативная под gevent —
Locust монки-патчит стандартный socket/ssl модуль через gevent при старте, так
что websocket-client работает конкурентно "из коробки", без asyncio-моста).

Формат протокола — см. app/chats/routes/v1/ws.py и app/chats/schemas/ws.py:
  - токен передаётся query-параметром ?token=... (app/core/api/utils.py::get_ws_access_token)
  - авто-subscribe при коннекте требует ОБА параметра initial_chat_id И
    initial_last_seq (иначе SubscribeCommand не вызывается вообще — см.
    websocket_gateway: `if initial_chat_id is not None and initial_last_seq is not None`)
  - клиентские команды: {"op": "subscribe"/"unsubscribe"/"resume"/"ping"/"pong", ...}
"""
from __future__ import annotations

import json
from urllib.parse import urlencode

import websocket

from loadtests.common.settings import API_V1_STR, WS_BASE_URL


def build_ws_url(
    token: str,
    initial_chat_id: str | None = None,
    initial_last_seq: int | None = None,
    device_id: str | None = None,
) -> str:
    params: dict[str, str] = {"token": token}
    if device_id:
        params["device_id"] = device_id
    if initial_chat_id is not None and initial_last_seq is not None:
        params["initial_chat_id"] = initial_chat_id
        params["initial_last_seq"] = str(initial_last_seq)
    return f"{WS_BASE_URL}{API_V1_STR}/chats/ws/?{urlencode(params)}"


class WSClient:
    def __init__(self, url: str, connect_timeout: float = 10.0) -> None:
        self.ws = websocket.create_connection(
            url,
            timeout=connect_timeout,
            subprotocols=["chat.v1"],
        )

    def send_json(self, obj: dict) -> None:
        self.ws.send(json.dumps(obj))

    def recv_json(self, timeout: float | None = None) -> dict:
        if timeout is not None:
            self.ws.settimeout(timeout)
        raw = self.ws.recv()
        if raw == "":
            raise ConnectionError("WS closed by server (empty frame)")
        return json.loads(raw)

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass
