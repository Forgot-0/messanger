import asyncio

import pytest
from httpx import AsyncClient

from app.chats.config import chat_config
from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import direct_chat_payload, group_chat_payload, send_text_payload
from tests.chats.integration.ws_asgi_client import AsyncASGIWebSocketSession, recv_until_type
from tests.support.http import api_path


async def _create_chat(client: AsyncClient, headers: dict[str, str], payload: dict) -> str:
    response = await client.post(api_path("chats/"), json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _send(client: AsyncClient, headers: dict[str, str], chat_id: str, content: str) -> dict:
    response = await client.post(
        api_path(f"chats/{chat_id}/messages/"), json=send_text_payload(content), headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestForwardManyHttp:
    async def test_batch_is_idempotent_and_ordered(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        source = await _create_chat(client, headers, group_chat_payload(name="src", member_ids=[2]))
        target = await _create_chat(client, headers, group_chat_payload(name="dst", member_ids=[2]))
        sent = [await _send(client, headers, source, f"m{i}") for i in range(3)]
        payload = {
            "source_chat_id": source,
            "source_message_ids": [m["id"] for m in reversed(sent)],
            "comment": "fyi",
        }
        retry_headers = {**headers, "Idempotency-Key": "batch-1"}

        first = await client.post(
            api_path(f"chats/{target}/messages/forward_many/"), json=payload, headers=retry_headers
        )
        second = await client.post(
            api_path(f"chats/{target}/messages/forward_many/"), json=payload, headers=retry_headers
        )

        assert first.status_code == 201, first.text
        assert second.status_code == 201
        assert first.json() == second.json()
        body = first.json()["messages"]
        assert [m["content"] for m in body] == ["fyi", "m0", "m1", "m2"]
        assert [m["type"] for m in body] == ["text", "forward", "forward", "forward"]

        history = await client.get(api_path(f"chats/{target}/messages/"), headers=headers)
        assert len(history.json()["messages"]) == 4

    async def test_validation(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await _create_chat(client, headers, group_chat_payload(member_ids=[2]))
        url = api_path(f"chats/{chat_id}/messages/forward_many/")

        empty = await client.post(url, json={"source_chat_id": chat_id, "source_message_ids": []}, headers=headers)
        too_many = await client.post(
            url,
            json={
                "source_chat_id": chat_id,
                "source_message_ids": [
                    "00000000-0000-7000-8000-000000000000"
                ] * (chat_config.MAX_FORWARD_MESSAGES + 1),
            },
            headers=headers,
        )

        assert empty.status_code == 422
        assert too_many.status_code == 422


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestPinnedMessagesHttp:
    async def test_pin_list_unpin_flow(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner = create_auth_headers(user_jwt)
        member = create_auth_headers(make_user_jwt(id="2"))
        chat_id = await _create_chat(client, owner, group_chat_payload(member_ids=[2]))
        first = await _send(client, owner, chat_id, "rules")
        second = await _send(client, owner, chat_id, "faq")
        base = api_path(f"chats/{chat_id}/pinned_messages/")

        pinned = await client.put(f"{base}{first['id']}/", headers=owner)
        assert pinned.status_code == 200, pinned.text
        assert pinned.json()["message"]["id"] == first["id"]
        assert pinned.json()["pinned_by"] == 1
        assert (await client.put(f"{base}{second['id']}/", headers=owner)).status_code == 200

        denied = await client.put(f"{base}{first['id']}/", headers=member)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "CHAT_ACCESS_DENIED"

        listed = await client.get(base, headers=member)
        assert listed.status_code == 200
        assert [item["message"]["content"] for item in listed.json()["items"]] == ["faq", "rules"]
        assert listed.json()["total"] == 2

        history = await client.get(api_path(f"chats/{chat_id}/messages/"), headers=member)
        notices = [m for m in history.json()["messages"] if m["type"] == "system"]
        assert [(n["action"], n["reply_to_id"]) for n in notices] == [
            ("message_pinned", second["id"]),
            ("message_pinned", first["id"]),
        ]
        assert notices[0]["reply_to"]["content"] == "faq"

        assert (await client.delete(f"{base}{first['id']}/", headers=owner)).status_code == 204
        assert (await client.delete(f"{base}{first['id']}/", headers=owner)).status_code == 204
        assert (await client.get(base, headers=owner)).json()["total"] == 1

        assert (await client.delete(base, headers=owner)).status_code == 204
        empty = (await client.get(base, headers=owner)).json()
        assert empty == {"items": [], "total": 0, "has_next": False, "next_cursor": None}


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMessageReadsHttp:
    async def test_reads_in_a_group_and_refusal_in_a_direct_chat(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        group = await _create_chat(client, headers, group_chat_payload(member_ids=[2]))
        direct = await _create_chat(client, headers, direct_chat_payload(peer_user_id=2))
        in_group = await _send(client, headers, group, "seen?")
        in_direct = await _send(client, headers, direct, "seen?")

        reads = await client.get(api_path(f"chats/{group}/messages/{in_group['id']}/reads/"), headers=headers)
        assert reads.status_code == 200, reads.text
        assert reads.json() == {"message_id": in_group["id"], "readers": []}

        refused = await client.get(api_path(f"chats/{direct}/messages/{in_direct['id']}/reads/"), headers=headers)
        assert refused.status_code == 400
        assert refused.json()["error"]["code"] == "READ_RECEIPTS_UNAVAILABLE"
        assert refused.json()["error"]["detail"]["reason"] == "chat_type"


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestTypingOverWebSocket:
    async def test_typing_op_is_routed_and_errors_come_back_as_ws_error(
        self,
        app,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
        create_access_token,
        go_online,
        delivered_frames,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        direct = await _create_chat(client, headers, direct_chat_payload(peer_user_id=2))
        foreign = await _create_chat(
            client, create_auth_headers(make_user_jwt(id="3")), group_chat_payload(member_ids=[4])
        )
        await go_online(2)

        async with AsyncASGIWebSocketSession(
            app, path=api_path("chats/ws/"), query={"token": create_access_token(user_jwt)}
        ) as ws:
            assert (await ws.recv_event())["type"] == "ws.ready"

            await ws.send_json({"op": "typing", "chat_id": direct, "action": "record_voice"})
            await ws.send_json({"op": "typing", "chat_id": foreign})
            error = await recv_until_type(ws, "ws.error")
            assert error["code"] == "NOT_FOUND_CHAT"

            await ws.send_json({"op": "typing", "chat_id": direct, "action": "dance"})
            bad = await recv_until_type(ws, "ws.error")
            assert bad["code"] == "BAD_COMMAND"

        frames = []
        for _ in range(50):
            frames = await delivered_frames()
            if frames:
                break
            await asyncio.sleep(0.05)

        assert [frame["type"] for frame in frames] == ["typing_start"]
        assert frames[0]["channel"] == direct
        assert frames[0]["payload"]["event"]["action"] == "record_voice"
        assert frames[0]["delivery"]["recipients"] == [2]
