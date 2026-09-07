from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import direct_chat_payload, group_chat_payload, send_text_payload
from tests.support.http import api_path


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestChatsHttpEndpoints:
    async def test_list_chats_unauthorized(self, client: AsyncClient) -> None:
        response = await client.get(api_path("chats/"))
        assert response.status_code == 403

    async def test_create_list_get_update_delete_flow(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        create_resp = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Lifecycle Group"),
            headers=headers,
        )
        assert create_resp.status_code == 201
        chat_id = create_resp.json()["id"]

        list_resp = await client.get(api_path("chats/"), headers=headers)
        assert list_resp.status_code == 200
        listed_ids = {c["id"] for c in list_resp.json()["chats"]}
        assert chat_id in listed_ids

        detail_resp = await client.get(api_path(f"chats/{chat_id}/"), headers=headers)
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == chat_id
        assert detail["name"] == "Lifecycle Group"

        patch_resp = await client.patch(
            api_path(f"chats/{chat_id}/"),
            json={"name": "Renamed Group", "description": "updated"},
            headers=headers,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["name"] == "Renamed Group"

        delete_resp = await client.delete(api_path(f"chats/{chat_id}/"), headers=headers)
        assert delete_resp.status_code == 204

        gone = await client.get(api_path(f"chats/{chat_id}/"), headers=headers)
        assert gone.status_code == 404
        assert gone.json()["error"]["code"] == "NOT_FOUND_CHAT"

    async def test_get_chat_not_found(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        missing = uuid4()
        response = await client.get(api_path(f"chats/{missing}/"), headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_CHAT"

    async def test_stranger_not_chat_member_on_detail(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        create_resp = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Private to owner"),
            headers=owner_headers,
        )
        assert create_resp.status_code == 201
        chat_id = create_resp.json()["id"]

        stranger = make_user_jwt(id="99999", username="stranger99999")
        response = await client.get(
            api_path(f"chats/{chat_id}/"),
            headers=create_auth_headers(stranger),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "NOT_CHAT_MEMBER"

    async def test_public_group_join_and_leave(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        create_resp = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Public Lounge", is_public=True),
            headers=owner_headers,
        )
        assert create_resp.status_code == 201
        chat_id = create_resp.json()["id"]

        joiner = make_user_jwt(id="50010", username="joiner50010")
        join_headers = create_auth_headers(joiner)

        join_resp = await client.post(api_path(f"chats/{chat_id}/join/"), headers=join_headers)
        assert join_resp.status_code == 204

        detail = await client.get(api_path(f"chats/{chat_id}/"), headers=join_headers)
        assert detail.status_code == 200

        leave_resp = await client.post(api_path(f"chats/{chat_id}/leave/"), headers=join_headers)
        assert leave_resp.status_code == 204

        forbidden = await client.get(api_path(f"chats/{chat_id}/"), headers=join_headers)
        assert forbidden.status_code == 403

    async def test_join_non_public_chat_forbidden(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        create_resp = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Closed Group", is_public=False),
            headers=owner_headers,
        )
        assert create_resp.status_code == 201
        chat_id = create_resp.json()["id"]

        joiner = make_user_jwt(id="50011", username="joiner50011")
        response = await client.post(
            api_path(f"chats/{chat_id}/join/"),
            headers=create_auth_headers(joiner),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CHAT_ACCESS_DENIED"

    async def test_direct_chat_create(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        response = await client.post(
            api_path("chats/"),
            json=direct_chat_payload(peer_user_id=50_020),
            headers=headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "direct"

    async def test_list_chats_cursor_pagination(
        self,
        client: AsyncClient,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        isolated = make_user_jwt(id="91001", username="chatpager91001")
        headers = create_auth_headers(isolated)
        uid = int(isolated.id)
        created_ids: list[str] = []
        for i in range(3):
            resp = await client.post(
                api_path("chats/"),
                json=group_chat_payload(name=f"Page chat {i}", member_ids=[uid]),
                headers=headers,
            )
            assert resp.status_code == 201
            cid = resp.json()["id"]
            created_ids.append(cid)
            bump = await client.post(
                api_path(f"chats/{cid}/messages/"),
                json=send_text_payload("activity"),
                headers=headers,
            )
            assert bump.status_code == 201

        first = await client.get(api_path("chats/"), params={"limit": 2}, headers=headers)
        assert first.status_code == 200
        body = first.json()
        assert len(body["chats"]) == 2
        assert body["has_next"] is True
        assert body["next_chat_id"] is not None
        ids_first = {str(c["id"]) for c in body["chats"]}
        assert ids_first.issubset(set(created_ids))

        if body["next_date"] is not None:
            second = await client.get(
                api_path("chats/"),
                params={
                    "limit": 2,
                    "last_chat_id": str(body["next_chat_id"]),
                    "last_activity_at": body["next_date"],
                },
                headers=headers,
            )
            assert second.status_code == 200
            assert second.json()["has_next"] in (True, False)
