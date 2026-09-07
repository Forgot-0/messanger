import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import group_chat_payload, send_text_payload
from tests.chats.integration.ws_asgi_client import (
    AsyncASGIWebSocketSession,
    recv_until_type,
)
from tests.support.http import api_path


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestWebSocketSubscribeAccess:

    async def test_subscribe_to_foreign_chat_returns_error(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_access_token,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Private WS chat"),
            headers=owner_headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        stranger = make_user_jwt(id="70001", username="stranger_ws")
        token = create_access_token(stranger)

        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            assert (await ws.recv_event())["type"] == "ws.ready"

            await ws.send_json({"op": "subscribe", "chat_id": chat_id, "last_seq": 0})

            err = await ws.recv_event()
            assert err["type"] == "ws.error"
            assert err.get("code") in ("NOT_CHAT_MEMBER", "BAD_COMMAND", "FORBIDDEN")

    async def test_banned_member_cannot_subscribe(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_access_token,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)

        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Ban WS test", member_ids=[1, 70002]),
            headers=owner_headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        ban = await client.patch(
            api_path(f"chats/{chat_id}/members/70002/ban/"),
            json={"ban": True},
            headers=owner_headers,
        )
        assert ban.status_code == 204

        banned = make_user_jwt(id="70002", username="banned_ws_user")
        token = create_access_token(banned)

        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            await ws.recv_event()
            await ws.send_json({"op": "subscribe", "chat_id": chat_id, "last_seq": 0})

            err = await ws.recv_event()
            assert err["type"] == "ws.error"


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestWebSocketResumeWithRealSeq:
    async def test_resume_delivers_missed_messages(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Resume test"),
            headers=headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        seqs = []
        for i in range(3):
            resp = await client.post(
                api_path(f"chats/{chat_id}/messages/"),
                json=send_text_payload(f"message {i}"),
                headers=headers,
            )
            assert resp.status_code == 201
            seqs.append(resp.json()["seq"])

        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            await ws.recv_event()

            await ws.send_json({
                "op": "resume",
                "cursors": {chat_id: seqs[0]},
            })

            subscribed = await recv_until_type(ws, "ws.subscribed")
            assert subscribed["chat_id"] == chat_id

            history = await recv_until_type(ws, "ws.history")
            assert history["chat_id"] == chat_id
            payload = history["payload"]
            delivered_seqs = {m["seq"] for m in payload["messages"]}

            assert seqs[1] in delivered_seqs
            assert seqs[2] in delivered_seqs
            assert seqs[0] not in delivered_seqs

    async def test_resume_with_zero_seq_delivers_all_messages(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Resume from zero"),
            headers=headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        for i in range(2):
            resp = await client.post(
                api_path(f"chats/{chat_id}/messages/"),
                json=send_text_payload(f"msg {i}"),
                headers=headers,
            )
            assert resp.status_code == 201

        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            await ws.recv_event()

            await ws.send_json({"op": "resume", "cursors": {chat_id: 0}})
            await recv_until_type(ws, "ws.subscribed")
            history = await recv_until_type(ws, "ws.history")

            assert len(history["payload"]["messages"]) >= 2

    async def test_resume_with_latest_seq_returns_empty_history(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Resume up-to-date"),
            headers=headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        resp = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("last message"),
            headers=headers,
        )
        assert resp.status_code == 201
        last_seq = resp.json()["seq"]

        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            await ws.recv_event()

            await ws.send_json({"op": "resume", "cursors": {chat_id: last_seq}})
            await recv_until_type(ws, "ws.subscribed")
            history = await recv_until_type(ws, "ws.history")

            assert history["payload"]["has_more"] is False
            assert len(history["payload"]["messages"]) == 0

    async def test_subscribe_with_last_seq_delivers_missed_messages(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Subscribe replay"),
            headers=headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        sent_seqs = []
        for i in range(4):
            resp = await client.post(
                api_path(f"chats/{chat_id}/messages/"),
                json=send_text_payload(f"msg {i}"),
                headers=headers,
            )
            assert resp.status_code == 201
            sent_seqs.append(resp.json()["seq"])

        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            await ws.recv_event()

            await ws.send_json({
                "op": "subscribe",
                "chat_id": chat_id,
                "last_seq": sent_seqs[1],
            })

            await recv_until_type(ws, "ws.subscribed")
            history = await recv_until_type(ws, "ws.history")

            delivered = {m["seq"] for m in history["payload"]["messages"]}
            assert sent_seqs[2] in delivered
            assert sent_seqs[3] in delivered
            assert sent_seqs[0] not in delivered
            assert sent_seqs[1] not in delivered
