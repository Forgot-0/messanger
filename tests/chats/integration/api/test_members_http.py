from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc
from app.core.websocket.keys import WebsocketKeys
from tests.chats.integration.factories import group_chat_payload
from tests.support.http import api_path


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMembersHttpEndpoints:
    async def test_list_members(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Members list", member_ids=[1, 50_100]),
            headers=headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        response = await client.get(api_path(f"chats/{chat_id}/members/"), headers=headers)
        assert response.status_code == 200
        payload = response.json()
        user_ids = {m["user_id"] for m in payload["members"]}
        assert 1 in user_ids
        assert 50_100 in user_ids

    async def test_add_kick_member_flow(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Kick flow"),
            headers=owner_headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        target_id = 50_101
        add = await client.post(
            api_path(f"chats/{chat_id}/members/"),
            json={"user_id": target_id, "role_id": 5},
            headers=owner_headers,
        )
        assert add.status_code == 204

        victim = make_user_jwt(id=str(target_id), username="kickvictim")
        victim_headers = create_auth_headers(victim)
        assert (await client.get(api_path(f"chats/{chat_id}/"), headers=victim_headers)).status_code == 200

        kick = await client.delete(
            api_path(f"chats/{chat_id}/members/{target_id}/"),
            headers=owner_headers,
        )
        assert kick.status_code == 204

        blocked = await client.get(api_path(f"chats/{chat_id}/"), headers=victim_headers)
        assert blocked.status_code == 403

    async def test_add_member_duplicate_conflict(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Dup members"),
            headers=headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        first = await client.post(
            api_path(f"chats/{chat_id}/members/"),
            json={"user_id": 50_102, "role_id": 5},
            headers=headers,
        )
        assert first.status_code == 204

        second = await client.post(
            api_path(f"chats/{chat_id}/members/"),
            json={"user_id": 50_102, "role_id": 5},
            headers=headers,
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "ALREADY_CHAT_MEMBER"

    async def test_ban_and_unban_blocks_messages(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        target_id = 50_103
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Ban flow", member_ids=[1, target_id]),
            headers=owner_headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        victim_headers = create_auth_headers(make_user_jwt(id=str(target_id), username="banneduser"))

        ban = await client.patch(
            api_path(f"chats/{chat_id}/members/{target_id}/ban/"),
            json={},
            headers=owner_headers,
        )
        assert ban.status_code == 204

        denied = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json={"content": "should fail", "message_type": "text", "upload_tokens": []},
            headers=victim_headers,
        )
        assert denied.status_code == 403

        unban = await client.patch(
            api_path(f"chats/{chat_id}/members/{target_id}/ban/"),
            json={"banned_to": (now_utc() - timedelta(days=1)).isoformat()},
            headers=owner_headers,
        )
        assert unban.status_code == 204

        ok = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json={"content": "back online", "message_type": "text", "upload_tokens": []},
            headers=victim_headers,
        )
        assert ok.status_code == 201

    async def test_change_member_role(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        target_id = 50_104
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Role change", member_ids=[1, target_id]),
            headers=headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        role_change = await client.patch(
            api_path(f"chats/{chat_id}/members/{target_id}/role/"),
            json={"role_id": 3},
            headers=headers,
        )
        assert role_change.status_code == 204

        listed = await client.get(api_path(f"chats/{chat_id}/members/"), headers=headers)
        assert listed.status_code == 200
        by_user = {m["user_id"]: m for m in listed.json()["members"]}
        assert by_user[target_id]["role_id"] == 3

    async def test_list_members_include_presence_marks_online_from_redis(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        redis_client,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        peer_id = 50_150
        await redis_client.zadd(
            WebsocketKeys.presence_last_seen_zset(),
            {str(peer_id): now_utc().timestamp()},
        )

        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Presence flags", member_ids=[1, peer_id]),
            headers=headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        response = await client.get(
            api_path(f"chats/{chat_id}/members/"),
            params={"include_presence": "true"},
            headers=headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["presence"]
        by_uid = {p["user_id"]: p["is_online"] for p in payload["presence"]}
        assert by_uid.get(peer_id) is True
