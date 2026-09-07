"""
Общая логика ожидания ack на subscribe/resume — используется и в
ws_fanout.py (подтвердить, что читатель реально подписался, а не просто
открыл TCP-соединение), и в ws_churn.py (это буквально предмет сценария).

Вынесено в common/ после находки в ws_fanout.py: без явной проверки ack
"успешный коннект" (ws_connect) ничего не говорит о том, что подписка
реально прошла — сервер мог прислать ws.error (например, если у пользователя
уже 2 активных соединения, см. WS_MAX_CONNECTIONS_PER_USER в
app/chats/config.py и ChatConnectionManager.register в app/chats/services/ws.py,
который в этом случае молча закрывает САМОЕ СТАРОЕ соединение того же
user_id, а не отклоняет новое) — и это осталось бы незамеченным.
"""
from __future__ import annotations

import time

import websocket

from loadtests.common.ws_client import WSClient


def wait_for_subscribe_ack(client: WSClient, deadline_s: float) -> tuple[bool, int | None, str | None]:
    """Ждём ws.subscribed + ws.history (именно в этом порядке шлёт
    SubscribeCommandHandler, см. app/chats/commands/websockets/subscribe.py)
    или ws.error. Возвращает (успех, next_last_seq, код_ошибки)."""
    remaining = deadline_s
    last_seq: int | None = None

    while remaining > 0:
        started = time.monotonic()
        try:
            frame = client.recv_json(timeout=remaining)
        except websocket.WebSocketTimeoutException:
            return False, None, "TIMEOUT"
        except Exception as exc:  # noqa: BLE001 - соединение могло быть закрыто сервером
            return False, None, f"CONNECTION_ERROR: {exc}"
        remaining -= time.monotonic() - started

        frame_type = frame.get("type")
        if frame_type == "ws.error":
            return False, None, frame.get("code", "UNKNOWN_ERROR")
        if frame_type == "ws.subscribed":
            payload = frame.get("payload") or {}
            if payload.get("last_seq") is not None:
                last_seq = payload["last_seq"]
            continue
        if frame_type == "ws.history":
            payload = frame.get("payload") or {}
            last_seq = payload.get("next_last_seq", last_seq)
            return True, last_seq, None
        if frame_type == "ws.ready":
            continue
        # Прочие события (new_message и т.п.), случайно пришедшие во время
        # ack-ожидания, игнорируем — они не относятся к самому ack.

    return False, last_seq, "TIMEOUT"
