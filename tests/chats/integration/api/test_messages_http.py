from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import group_chat_payload, send_text_payload
from tests.support.http import api_path


async def _create_group_chat(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "Messages Test Chat",
    member_ids: list[int] | None = None,
    slow_mode_seconds: int = 0,
) -> str:
    payload = group_chat_payload(name=name, member_ids=member_ids, slow_mode_seconds=slow_mode_seconds)
    response = await client.post(api_path("chats/"), json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMessagesHttpEndpoints:
    async def test_send_list_get_edit_delete_flow(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        create_profile
    ) -> None:
        headers = create_auth_headers(user_jwt)
        await create_profile(user_jwt)
        chat_id = await _create_group_chat(client, headers)

        send_resp = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("hello world"),
            headers=headers,
        )
        assert send_resp.status_code == 201
        body = send_resp.json()
        message_id = body["id"]
        assert body["content"] == "hello world"
        assert body["seq"] >= 1

        list_resp = await client.get(api_path(f"chats/{chat_id}/messages/"), headers=headers)
        assert list_resp.status_code == 200
        listed = list_resp.json()
        assert listed["has_next"] in (True, False)
        ids = {m["id"] for m in listed["messages"]}
        assert message_id in ids

        one = await client.get(
            api_path(f"chats/{chat_id}/messages/{message_id}/"),
            headers=headers,
        )
        assert one.status_code == 200
        assert one.json()["id"] == message_id

        edited = await client.patch(
            api_path(f"chats/{chat_id}/messages/{message_id}/"),
            json={"content": "hello edited"},
            headers=headers,
        )
        assert edited.status_code == 200
        assert edited.json()["content"] == "hello edited"
        assert edited.json()["is_edited"] is True

        delete_resp = await client.delete(
            api_path(f"chats/{chat_id}/messages/{message_id}/"),
            headers=headers,
        )
        assert delete_resp.status_code == 204

    async def test_reply_to_message(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await _create_group_chat(client, headers)

        first = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("parent"),
            headers=headers,
        )
        assert first.status_code == 201
        parent_id = first.json()["id"]

        reply = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json={
                "content": "child reply",
                "reply_to_id": parent_id,
                "message_type": "text",
                "upload_tokens": [],
            },
            headers=headers,
        )
        assert reply.status_code == 201
        assert reply.json()["reply_to_id"] == parent_id

    async def test_message_context_and_mark_read(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await _create_group_chat(client, headers)

        send_resp = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("ctx anchor"),
            headers=headers,
        )
        assert send_resp.status_code == 201
        seq = send_resp.json()["seq"]

        ctx = await client.get(
            api_path(f"chats/{chat_id}/messages/context/"),
            params={"target_seq": seq, "limit": 10},
            headers=headers,
        )
        assert ctx.status_code == 200
        assert any(m["seq"] == seq for m in ctx.json()["messages"])

        read_resp = await client.post(
            api_path(f"chats/{chat_id}/messages/read/"),
            json={"message_seq": seq},
            headers=headers,
        )
        assert read_resp.status_code == 204

    async def test_forward_message_between_chats(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        source_id = await _create_group_chat(client, headers, name="Source")
        target_id = await _create_group_chat(client, headers, name="Target")

        src_msg = await client.post(
            api_path(f"chats/{source_id}/messages/"),
            json=send_text_payload("forward me"),
            headers=headers,
        )
        assert src_msg.status_code == 201
        source_message_id = src_msg.json()["id"]

        fwd = await client.post(
            api_path(f"chats/{target_id}/messages/forward/"),
            json={
                "source_chat_id": source_id,
                "source_message_id": source_message_id,
                "comment": None,
            },
            headers=headers,
        )
        assert fwd.status_code == 201
        assert fwd.json()["type"] == "forward"

    async def test_send_idempotency_returns_same_message(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await _create_group_chat(client, headers)
        idem_key = "idem-integration-1"

        first = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("idempotent body"),
            headers={**headers, "Idempotency-Key": idem_key},
        )
        assert first.status_code == 201
        first_id = first.json()["id"]

        second = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("different body ignored"),
            headers={**headers, "Idempotency-Key": idem_key},
        )
        assert second.status_code == 201
        assert second.json()["id"] == first_id

    async def test_slow_mode_blocks_second_message_for_member(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        member_jwt = make_user_jwt(id="50050", username="slowmember")
        member_headers = create_auth_headers(member_jwt)

        chat_id = await _create_group_chat(
            client,
            owner_headers,
            name="Slow chat",
            member_ids=[1, 50_050],
            slow_mode_seconds=300,
        )

        first = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("first"),
            headers=member_headers,
        )
        assert first.status_code == 201

        second = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("second too fast"),
            headers=member_headers,
        )
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "SLOW_MODE_LIMIT"

    async def test_not_member_cannot_send(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        chat_id = await _create_group_chat(client, owner_headers)

        outsider = make_user_jwt(id="50051", username="outsider")
        response = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("nope"),
            headers=create_auth_headers(outsider),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_CHAT"

    async def test_list_messages_cursor_pagination(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await _create_group_chat(client, headers, name="Pagination chat")
        for i in range(5):
            send = await client.post(
                api_path(f"chats/{chat_id}/messages/"),
                json=send_text_payload(f"msg-{i}"),
                headers=headers,
            )
            assert send.status_code == 201

        first = await client.get(
            api_path(f"chats/{chat_id}/messages/"),
            params={"limit": 2},
            headers=headers,
        )
        assert first.status_code == 200
        page1 = first.json()
        assert page1["has_next"] is True
        assert page1["next_cursor"] is not None

        second = await client.get(
            api_path(f"chats/{chat_id}/messages/"),
            params={"limit": 2, "cursor_message_seq": page1["next_cursor"]},
            headers=headers,
        )
        assert second.status_code == 200
        seqs_page1 = {m["seq"] for m in page1["messages"]}
        seqs_page2 = {m["seq"] for m in second.json()["messages"]}
        assert seqs_page1.isdisjoint(seqs_page2)

    async def test_get_message_detail_not_found(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await _create_group_chat(client, headers)
        missing = uuid4()
        response = await client.get(
            api_path(f"chats/{chat_id}/messages/{missing}/"),
            headers=headers,
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_MESSAGE"

    async def test_edit_message_forbidden_for_non_author(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        author_id = 50_060
        owner_headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Edit perms", member_ids=[1, author_id]),
            headers=owner_headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        author = make_user_jwt(id=str(author_id), username="msgauthor")
        author_headers = create_auth_headers(author)
        sent = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("by member"),
            headers=author_headers,
        )
        assert sent.status_code == 201
        message_id = sent.json()["id"]

        patch = await client.patch(
            api_path(f"chats/{chat_id}/messages/{message_id}/"),
            json={"content": "owner tries steal"},
            headers=owner_headers,
        )
        assert patch.status_code == 403
        assert patch.json()["error"]["code"] == "CHAT_ACCESS_DENIED"

    async def test_forward_deleted_source_message_fails(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        source_id = await _create_group_chat(client, headers, name="Fwd source del")
        target_id = await _create_group_chat(client, headers, name="Fwd target del")

        src_msg = await client.post(
            api_path(f"chats/{source_id}/messages/"),
            json=send_text_payload("to be deleted"),
            headers=headers,
        )
        assert src_msg.status_code == 201
        source_message_id = src_msg.json()["id"]

        delete_resp = await client.delete(
            api_path(f"chats/{source_id}/messages/{source_message_id}/"),
            headers=headers,
        )
        assert delete_resp.status_code == 204

        fwd = await client.post(
            api_path(f"chats/{target_id}/messages/forward/"),
            json={
                "source_chat_id": source_id,
                "source_message_id": source_message_id,
                "comment": None,
            },
            headers=headers,
        )
        assert fwd.status_code == 404
        assert fwd.json()["error"]["code"] == "NOT_FOUND_MESSAGE"


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestClientMessageTypeContract:
    """SYSTEM обходил проверки контента, FORWARD оставлял пустые forwarded_from_*."""

    @pytest.mark.parametrize("message_type", ["system", "forward"])
    async def test_server_only_message_types_are_rejected(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        message_type: str,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        created = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Client type guard"),
            headers=headers,
        )
        assert created.status_code == 201
        chat_id = created.json()["id"]

        response = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json={"content": "x", "message_type": message_type},
            headers=headers,
        )
        assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestIdempotentWrites:
    async def test_send_with_same_key_returns_the_same_message(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await _create_group_chat(client, headers, name="Idempotent send")
        headers = {**headers, "Idempotency-Key": "send-retry-1"}

        first = await client.post(
            api_path(f"chats/{chat_id}/messages/"), json=send_text_payload("hi"), headers=headers
        )
        second = await client.post(
            api_path(f"chats/{chat_id}/messages/"), json=send_text_payload("hi"), headers=headers
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["seq"] == second.json()["seq"]

        listed = await client.get(api_path(f"chats/{chat_id}/messages/"), headers=headers)
        assert len(listed.json()["messages"]) == 1

    async def test_different_keys_create_different_messages(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await _create_group_chat(client, headers, name="Idempotent send 2")

        first = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("hi"),
            headers={**headers, "Idempotency-Key": "a"},
        )
        second = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("hi"),
            headers={**headers, "Idempotency-Key": "b"},
        )

        assert first.json()["id"] != second.json()["id"]

    async def test_forward_is_idempotent_too(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        source_id = await _create_group_chat(client, headers, name="Forward source")
        target_id = await _create_group_chat(client, headers, name="Forward target")

        sent = await client.post(
            api_path(f"chats/{source_id}/messages/"),
            json=send_text_payload("to forward"),
            headers=headers,
        )
        assert sent.status_code == 201

        forward_headers = {**headers, "Idempotency-Key": "forward-retry-1"}
        payload = {
            "source_chat_id": source_id,
            "source_message_id": sent.json()["id"],
        }

        first = await client.post(
            api_path(f"chats/{target_id}/messages/forward/"), json=payload, headers=forward_headers
        )
        second = await client.post(
            api_path(f"chats/{target_id}/messages/forward/"), json=payload, headers=forward_headers
        )

        assert first.status_code == 201
        assert first.json()["id"] == second.json()["id"]

        listed = await client.get(api_path(f"chats/{target_id}/messages/"), headers=headers)
        assert len(listed.json()["messages"]) == 1
