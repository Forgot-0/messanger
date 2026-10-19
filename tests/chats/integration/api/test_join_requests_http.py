import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import group_chat_payload
from tests.support.http import api_path


async def _create_chat(client: AsyncClient, headers: dict[str, str], payload: dict) -> str:
    response = await client.post(api_path("chats/"), json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _request_link(client: AsyncClient, headers: dict[str, str], chat_id: str) -> str:
    response = await client.post(
        api_path(f"chats/{chat_id}/invites/"),
        json={"creates_join_request": True, "name": "by request"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["creates_join_request"] is True
    return response.json()["code"]


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestJoinRequestsHttp:
    async def test_approve_flow(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner = create_auth_headers(user_jwt)
        applicant = create_auth_headers(make_user_jwt(id="70"))
        chat_id = await _create_chat(client, owner, group_chat_payload(member_ids=[2]))
        code = await _request_link(client, owner, chat_id)

        preview = await client.get(api_path(f"chats/invites/{code}/"), headers=applicant)
        assert preview.status_code == 200, preview.text
        assert preview.json()["creates_join_request"] is True
        assert preview.json()["join_request_status"] is None

        join = await client.post(api_path(f"chats/invites/{code}/join/"), headers=applicant)
        assert join.status_code == 200, join.text
        assert join.json()["status"] == "requested"
        assert join.json()["chat"] is None

        after = await client.get(api_path(f"chats/invites/{code}/"), headers=applicant)
        assert after.json()["join_request_status"] == "pending"

        pending = await client.get(api_path(f"chats/{chat_id}/join_requests/"), headers=owner)
        assert pending.status_code == 200, pending.text
        assert pending.json()["total"] == 1
        assert [item["user_id"] for item in pending.json()["requests"]] == [70]

        forbidden = await client.get(
            api_path(f"chats/{chat_id}/join_requests/"), headers=applicant
        )
        assert forbidden.status_code == 403

        approve = await client.post(
            api_path(f"chats/{chat_id}/join_requests/70/approve/"), headers=owner
        )
        assert approve.status_code == 204, approve.text

        members = await client.get(api_path(f"chats/{chat_id}/members/"), headers=owner)
        assert 70 in [member["user_id"] for member in members.json()["members"]]

        empty = await client.get(api_path(f"chats/{chat_id}/join_requests/"), headers=owner)
        assert empty.json()["total"] == 0

    async def test_decline_and_cancel(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner = create_auth_headers(user_jwt)
        declined = create_auth_headers(make_user_jwt(id="71"))
        withdrawn = create_auth_headers(make_user_jwt(id="72"))
        chat_id = await _create_chat(client, owner, group_chat_payload(member_ids=[2]))
        code = await _request_link(client, owner, chat_id)

        await client.post(api_path(f"chats/invites/{code}/join/"), headers=declined)
        await client.post(api_path(f"chats/invites/{code}/join/"), headers=withdrawn)

        decline = await client.post(
            api_path(f"chats/{chat_id}/join_requests/71/decline/"), headers=owner
        )
        assert decline.status_code == 204, decline.text

        retry = await client.post(api_path(f"chats/invites/{code}/join/"), headers=declined)
        assert retry.status_code == 429
        assert retry.json()["error"]["code"] == "JOIN_REQUEST_RETRY_LATER"

        cancel = await client.delete(
            api_path(f"chats/{chat_id}/join_requests/me/"), headers=withdrawn
        )
        assert cancel.status_code == 204, cancel.text

        repeat = await client.delete(
            api_path(f"chats/{chat_id}/join_requests/me/"), headers=withdrawn
        )
        assert repeat.status_code == 404

        pending = await client.get(api_path(f"chats/{chat_id}/join_requests/"), headers=owner)
        assert pending.json()["total"] == 0

    async def test_join_by_request_toggle_on_public_chat(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner = create_auth_headers(user_jwt)
        applicant = create_auth_headers(make_user_jwt(id="73"))
        chat_id = await _create_chat(
            client, owner, group_chat_payload(member_ids=[2], is_public=True)
        )

        updated = await client.patch(
            api_path(f"chats/{chat_id}/"), json={"join_by_request": True}, headers=owner
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["join_by_request"] is True

        join = await client.post(api_path(f"chats/{chat_id}/join/"), headers=applicant)
        assert join.status_code == 200, join.text
        assert join.json()["status"] == "requested"
        assert join.json()["join_request"]["user_id"] == 73

        pending = await client.get(api_path(f"chats/{chat_id}/join_requests/"), headers=owner)
        assert [item["user_id"] for item in pending.json()["requests"]] == [73]
