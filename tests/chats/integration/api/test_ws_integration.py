
import pytest
from httpx import AsyncClient

from app.chats.config import chat_config
from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import group_chat_payload
from tests.chats.integration.ws_asgi_client import (
    AsyncASGIWebSocketSession,
    WebSocketDenied,
    recv_until_type,
)
from tests.support.http import api_path


def _ws_path() -> str:
    return api_path("chats/ws/")


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatsWebSocketIntegration:
    async def test_missing_token_denied_before_accept(
        self,
        app,
        client: AsyncClient,
    ) -> None:
        await client.get(api_path("chats/"))
        with pytest.raises(WebSocketDenied) as exc:
            async with AsyncASGIWebSocketSession(app, path=_ws_path()):
                pass
        assert exc.value.code == 1008

    async def test_ready_ping_pong_with_query_token_and_subprotocol(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
    ) -> None:
        await client.get(api_path("chats/"))
        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(
            app,
            path=_ws_path(),
            query={"token": token},
            subprotocols=["chat.v1", "test"],
        ) as ws:
            assert ws.accepted_subprotocol == "chat.v1"
            ready = await ws.recv_event()
            assert ready["type"] == "ws.ready"
            assert ready["payload"]["connection_id"]
            assert ready["payload"]["gateway_id"]
            assert "heartbeat_interval" in ready["payload"]

            await ws.send_json({"op": "ping"})
            pong = await ws.recv_event()
            assert pong["type"] == "ws.pong"

    async def test_token_via_authorization_header(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
    ) -> None:
        await client.get(api_path("chats/"))
        token = create_access_token(user_jwt)
        headers = [(b"authorization", f"Bearer {token}".encode("latin-1"))]
        async with AsyncASGIWebSocketSession(app, path=_ws_path(), headers=headers) as ws:
            ready = await ws.recv_event()
            assert ready["type"] == "ws.ready"

    async def test_subscribe_unsubscribe_member_chat(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        created = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="WS member flow"),
            headers=headers,
        )
        assert created.status_code == 201
        chat_id = created.json()["id"]

        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(
            app,
            path=_ws_path(),
            query={"token": token},
        ) as ws:
            assert (await ws.recv_event())["type"] == "ws.ready"

            await ws.send_json({"op": "subscribe", "chat_id": chat_id, "last_seq": 0})
            sub = await recv_until_type(ws, "ws.subscribed")
            assert sub["chat_id"] == chat_id

            await ws.send_json({"op": "unsubscribe", "chat_id": chat_id})
            unsub = await recv_until_type(ws, "ws.unsubscribed")
            assert unsub["chat_id"] == chat_id

    async def test_subscribe_without_chat_id_returns_bad_command(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
    ) -> None:
        await client.get(api_path("chats/"))
        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(app, path=_ws_path(), query={"token": token}) as ws:
            await ws.recv_event()
            await ws.send_json({"op": "subscribe"})
            err = await ws.recv_event()
            assert err["type"] == "ws.error"
            assert err["code"] == "BAD_COMMAND"

    async def test_invalid_json_frame_returns_bad_frame(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
    ) -> None:
        await client.get(api_path("chats/"))
        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(app, path=_ws_path(), query={"token": token}) as ws:
            await ws.recv_event()
            await ws.send_raw_text("not-json{{{")
            err = await ws.recv_event()
            assert err["type"] == "ws.error"
            assert err["code"] == "BAD_FRAME"

    async def test_non_object_json_returns_bad_frame(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
    ) -> None:
        await client.get(api_path("chats/"))
        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(app, path=_ws_path(), query={"token": token}) as ws:
            await ws.recv_event()
            await ws.send_raw_text("[1,2,3]")
            err = await ws.recv_event()
            assert err["type"] == "ws.error"
            assert err["code"] == "BAD_FRAME"

    async def test_oversized_client_frame_returns_bad_frame(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
    ) -> None:
        await client.get(api_path("chats/"))
        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(app, path=_ws_path(), query={"token": token}) as ws:
            await ws.recv_event()
            huge = b"x" * (chat_config.WS_MAX_CLIENT_FRAME_BYTES + 1)
            await ws.send_bytes(huge)
            err = await ws.recv_event()
            assert err["type"] == "ws.error"
            assert err["code"] == "BAD_FRAME"
            assert "too large" in err.get("detail", "").lower()

    async def test_unknown_op_returns_bad_command(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
    ) -> None:
        await client.get(api_path("chats/"))
        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(app, path=_ws_path(), query={"token": token}) as ws:
            await ws.recv_event()
            await ws.send_json({"op": "not_a_real_op"})
            err = await ws.recv_event()
            assert err["type"] == "ws.error"
            assert err["code"] == "BAD_COMMAND"

    async def test_resume_with_empty_cursors_completes(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
    ) -> None:
        await client.get(api_path("chats/"))
        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(app, path=_ws_path(), query={"token": token}) as ws:
            await ws.recv_event()
            await ws.send_json({"op": "resume", "cursors": {}})
            await ws.send_json({"op": "ping"})
            pong = await ws.recv_event()
            assert pong["type"] == "ws.pong"
