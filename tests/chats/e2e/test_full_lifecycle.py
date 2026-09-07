
import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import group_chat_payload, send_text_payload
from tests.chats.integration.ws_asgi_client import (
    AsyncASGIWebSocketSession,
    recv_until_type,
)
from tests.support.http import api_path


@pytest.mark.e2e
@pytest.mark.chats
@pytest.mark.asyncio
class TestFullChatLifecycleE2E:

    async def test_create_send_receive_ws_mark_read_unread_zero(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
        create_auth_headers,
        create_profile,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        await create_profile(user_jwt)

        create_resp = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="E2E Lifecycle"),
            headers=headers,
        )
        assert create_resp.status_code == 201
        chat_id = create_resp.json()["id"]

        token = create_access_token(user_jwt)

        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            ready = await ws.recv_event()
            assert ready["type"] == "ws.ready"

            await ws.send_json({"op": "subscribe", "chat_id": chat_id, "last_seq": 0})
            subscribed = await recv_until_type(ws, "ws.subscribed")
            assert subscribed["chat_id"] == chat_id

            send_resp = await client.post(
                api_path(f"chats/{chat_id}/messages/"),
                json=send_text_payload("hello from e2e"),
                headers=headers,
            )
            assert send_resp.status_code == 201
            message_seq = send_resp.json()["seq"]

            event = None
            for _ in range(5):
                try:
                    event = await ws.recv_event()
                    if event.get("type") in ("ws.history", "new_message"):
                        break
                except TimeoutError:
                    break

            await ws.send_json({"op": "ping"})
            pong = await ws.recv_event()
            assert pong["type"] in ("ws.pong", "ws.history", "new_message")

        read_resp = await client.post(
            api_path(f"chats/{chat_id}/messages/read/"),
            json={"message_seq": message_seq},
            headers=headers,
        )
        assert read_resp.status_code == 204

        list_resp = await client.get(api_path("chats/"), headers=headers)
        assert list_resp.status_code == 200

        chat_in_list = next(
            (c for c in list_resp.json()["chats"] if c["id"] == chat_id),
            None,
        )
        assert chat_in_list is not None
        assert chat_in_list["unread_count"] == 0

    async def test_multiple_messages_unread_count_tracks_correctly(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        reader = make_user_jwt(id="80001", username="reader80001")
        reader_headers = create_auth_headers(reader)

        create_resp = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="E2E Unread", member_ids=[1, 80001]),
            headers=owner_headers,
        )
        assert create_resp.status_code == 201
        chat_id = create_resp.json()["id"]

        seqs = []
        for i in range(5):
            resp = await client.post(
                api_path(f"chats/{chat_id}/messages/"),
                json=send_text_payload(f"msg {i}"),
                headers=owner_headers,
            )
            assert resp.status_code == 201
            seqs.append(resp.json()["seq"])

        read_resp = await client.post(
            api_path(f"chats/{chat_id}/messages/read/"),
            json={"message_seq": seqs[2]},
            headers=reader_headers,
        )
        assert read_resp.status_code == 204

        list_resp = await client.get(api_path("chats/"), headers=reader_headers)
        assert list_resp.status_code == 200

        chat_in_list = next(
            (c for c in list_resp.json()["chats"] if c["id"] == chat_id),
            None,
        )
        assert chat_in_list is not None
        assert chat_in_list["unread_count"] == 2

    async def test_mark_read_then_new_message_increases_unread(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        reader = make_user_jwt(id="80002", username="reader80002")
        reader_headers = create_auth_headers(reader)

        create_resp = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="E2E Unread grow", member_ids=[1, 80002]),
            headers=owner_headers,
        )
        assert create_resp.status_code == 201
        chat_id = create_resp.json()["id"]

        resp1 = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("first"),
            headers=owner_headers,
        )
        seq1 = resp1.json()["seq"]

        await client.post(
            api_path(f"chats/{chat_id}/messages/read/"),
            json={"message_seq": seq1},
            headers=reader_headers,
        )

        list_resp = await client.get(api_path("chats/"), headers=reader_headers)
        chat = next(c for c in list_resp.json()["chats"] if c["id"] == chat_id)
        assert chat["unread_count"] == 0

        await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("second"),
            headers=owner_headers,
        )

        list_resp2 = await client.get(api_path("chats/"), headers=reader_headers)
        chat2 = next(c for c in list_resp2.json()["chats"] if c["id"] == chat_id)
        assert chat2["unread_count"] == 1

    async def test_ws_connection_survives_ping_pong(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_access_token,
    ) -> None:
        token = create_access_token(user_jwt)
        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": token}
        ) as ws:
            await ws.recv_event()

            for _ in range(3):
                await ws.send_json({"op": "ping"})
                pong = await ws.recv_event()
                assert pong["type"] == "ws.pong"

    async def test_chat_seq_counter_increments_per_message(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        create_resp = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="E2E Seq check"),
            headers=headers,
        )
        assert create_resp.status_code == 201
        chat_id = create_resp.json()["id"]

        seqs = []
        for i in range(5):
            resp = await client.post(
                api_path(f"chats/{chat_id}/messages/"),
                json=send_text_payload(f"msg {i}"),
                headers=headers,
            )
            assert resp.status_code == 201
            seqs.append(resp.json()["seq"])

        for i in range(1, len(seqs)):
            assert seqs[i] == seqs[i - 1] + 1, (
                f"seq не монотонный: {seqs[i - 1]} → {seqs[i]}"
            )
