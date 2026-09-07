import logging
from typing import Any

import orjson
from dishka import AsyncContainer
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.chats.commands.websockets.ping import PingCommand
from app.chats.commands.websockets.pong import PongCommand
from app.chats.commands.websockets.resume import ResumeCommand
from app.chats.commands.websockets.subscribe import SubscribeCommand
from app.chats.commands.websockets.unsubscribe import UnsubscribeCommand
from app.chats.config import chat_config
from app.chats.schemas.ws import WSClientCommand, WSClientOp
from app.core.api.utils import get_ws_access_token
from app.core.configs.app import app_config
from app.core.mediators.base import BaseMediator
from app.core.services.auth.dto import UserJWTData
from app.core.services.auth.jwt_manager import JWTManager
from app.core.websocket.manager import ConnectionManager
from app.core.websocket.websocket import WSConnection

router = APIRouter()
logger = logging.getLogger(__name__)



def _select_subprotocol(websocket: WebSocket) -> str | None:
    offered = {
        part.strip()
        for part in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if part.strip()
    }
    return "chat.v1" if "chat.v1" in offered else None


async def get_json_user(websocket: WebSocket) -> dict[str, Any]:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))

    raw: str | bytes | None = message.get("text") or message.get("bytes")
    if raw is None:
        raise ValueError("empty websocket frame")

    raw_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(raw_bytes) > chat_config.WS_MAX_CLIENT_FRAME_BYTES:
        raise ValueError("websocket frame is too large")

    data = orjson.loads(raw_bytes)
    if not isinstance(data, dict):
        raise ValueError("websocket frame must be a JSON object")
    return data


@router.websocket("/ws/")
@inject
async def websocket_gateway(
    websocket: WebSocket,
    container: FromDishka[AsyncContainer],
    initial_chat_id: str | None=None,
    initial_last_seq: int | None=None,
) -> None:
    token = get_ws_access_token(websocket)
    if not token:
        await websocket.close(code=1008, reason="missing token")
        return

    async with container() as request_container:
        jwt_manager = await request_container.get(JWTManager)
        user_jwt_data = UserJWTData.create_from_token(await jwt_manager.validate_token(token))
        user_id = int(user_jwt_data.id)

    await websocket.accept(subprotocol=_select_subprotocol(websocket))

    async with container() as request_container:
        manager = await request_container.get(ConnectionManager)

        conn = WSConnection(
            websocket=websocket,
            user_id=user_id,
            device_id=user_jwt_data.device_id or websocket.query_params.get("device_id") or "unknown",
            gateway_id=manager.gateway_id,
        )

        await manager.register(conn)
        conn.try_send(
            {
                "type": "ws.ready",
                "payload": {
                    "connection_id": conn.connection_id,
                    "gateway_id": conn.gateway_id,
                    "heartbeat_interval": app_config.WS_HEARTBEAT_INTERVAL,
                    "heartbeat_timeout": app_config.WS_HEARTBEAT_TIMEOUT,
                    "reconnect": {"mode": "last_seq_per_chat", "op": "resume"},
                },
            },
        )

        if initial_chat_id is not None and initial_last_seq is not None:
            async with container() as request_container:
                mediator = await request_container.get(BaseMediator)
                await mediator.handle_command(
                    SubscribeCommand(
                        conn=conn,
                        chat_id=initial_chat_id,
                        user_id=user_id,
                        last_seq=initial_last_seq
                    )
                )

    try:
        while True:
            try:
                payload = await get_json_user(websocket)
                conn.touch()
                websocket_command = WSClientCommand.model_validate(payload)
            except ValidationError as exc:
                message = exc.errors()[0].get("msg", "invalid command") if exc.errors() else "invalid command"
                conn.try_send({
                    "type": "ws.error",
                    "code": "BAD_COMMAND",
                    "detail": str(message),
                })
                continue
            except ValueError as exc:
                conn.try_send({
                    "type": "ws.error",
                    "code": "BAD_FRAME",
                    "detail": str(exc),
                })
                continue

            async with container() as request_container:
                mediator = await request_container.get(BaseMediator)
                match websocket_command.op:
                    case WSClientOp.RESUME:
                        await mediator.handle_command(
                            ResumeCommand(conn=conn, cursor=websocket_command.cursors)
                        )
                    case WSClientOp.SUBSCRIBE:
                        if websocket_command.chat_id is None:
                            conn.try_send({
                                "type": "ws.error",
                                "code": "BAD_COMMAND",
                                "detail": "chat_id is requeried",
                            })
                            continue
                        await mediator.handle_command(
                            SubscribeCommand(
                                conn=conn,
                                chat_id=websocket_command.chat_id,
                                user_id=conn.user_id,
                                last_seq=websocket_command.last_seq
                            )
                        )
                    case WSClientOp.PING:
                        await mediator.handle_command(PingCommand(conn=conn))
                    case WSClientOp.PONG:
                        await mediator.handle_command(PongCommand(conn=conn))
                    case WSClientOp.UNSUBSCRIBE:
                        if websocket_command.chat_id is None:
                            conn.try_send({
                                "type": "ws.error",
                                "code": "BAD_COMMAND",
                                "detail": "chat_id is requeried",
                            })
                            continue
                        await mediator.handle_command(
                            UnsubscribeCommand(conn=conn, chat_id=websocket_command.chat_id)
                        )
    except WebSocketDisconnect:
        pass
    finally:
        await manager.unregister(conn)
