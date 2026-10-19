from datetime import timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.models.blocks import ChatUserBlock
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc
from tests.chats.integration.factories import direct_chat_payload, group_chat_payload, send_text_payload
from tests.support.http import api_path

MEMBER_ID = 50_200
OTHER_ID = 50_201


async def create_group(client: AsyncClient, headers: dict[str, str], **kwargs) -> str:
    response = await client.post(
        api_path("chats/"),
        json=group_chat_payload(member_ids=[MEMBER_ID, OTHER_ID], **kwargs),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestModerationHttp:

    async def test_mute_and_unmute_member(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_group(client, headers)
        until = (now_utc() + timedelta(hours=1)).isoformat()

        mute = await client.patch(
            api_path(f"chats/{chat_id}/members/{MEMBER_ID}/mute/"), json={"muted_until": until}, headers=headers,
        )
        assert mute.status_code == 204

        members = (await client.get(api_path(f"chats/{chat_id}/members/"), headers=headers)).json()["members"]
        muted = next(member for member in members if member["user_id"] == MEMBER_ID)
        assert muted["is_muted"] is True
        assert muted["muted_until"] is not None

        unmute = await client.delete(api_path(f"chats/{chat_id}/members/{MEMBER_ID}/mute/"), headers=headers)
        assert unmute.status_code == 204

        members = (await client.get(api_path(f"chats/{chat_id}/members/"), headers=headers)).json()["members"]
        assert next(member for member in members if member["user_id"] == MEMBER_ID)["is_muted"] is False

    async def test_explicit_unban(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_group(client, headers)

        ban = await client.patch(api_path(f"chats/{chat_id}/members/{MEMBER_ID}/ban/"), json={}, headers=headers)
        assert ban.status_code == 204

        unban = await client.delete(api_path(f"chats/{chat_id}/members/{MEMBER_ID}/ban/"), headers=headers)
        assert unban.status_code == 204

        members = (await client.get(api_path(f"chats/{chat_id}/members/"), headers=headers)).json()["members"]
        assert MEMBER_ID in {member["user_id"] for member in members}

    async def test_transfer_ownership(
        self, client: AsyncClient, user_jwt: UserJWTData, make_user_jwt, create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_group(client, headers)

        response = await client.post(
            api_path(f"chats/{chat_id}/transfer_ownership/"), json={"user_id": MEMBER_ID}, headers=headers,
        )
        assert response.status_code == 204

        detail = (await client.get(api_path(f"chats/{chat_id}/"), headers=headers)).json()
        assert detail["created_by"] == MEMBER_ID
        roles = {member["user_id"]: member["role_id"] for member in detail["members"]}
        assert roles[MEMBER_ID] == 1
        assert roles[int(user_jwt.id)] == 2

        leave = await client.post(api_path(f"chats/{chat_id}/leave/"), headers=headers)
        assert leave.status_code == 204

        new_owner_headers = create_auth_headers(make_user_jwt(id=str(MEMBER_ID)))
        stuck = await client.post(api_path(f"chats/{chat_id}/leave/"), headers=new_owner_headers)
        assert stuck.status_code == 403

    async def test_username_resolve_and_search(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_group(client, headers, name="Kotlin Weekly", is_public=True)

        put = await client.put(api_path(f"chats/{chat_id}/username/"), json={"username": "KotlinWeekly"}, headers=headers)
        assert put.status_code == 200, put.text
        assert put.json()["username"] == "KotlinWeekly"

        resolved = await client.get(api_path("chats/u/kotlinweekly/"), headers=headers)
        assert resolved.status_code == 200
        assert resolved.json()["id"] == chat_id
        assert resolved.json()["is_member"] is True

        search = await client.get(api_path("chats/search/"), params={"q": "kotlin"}, headers=headers)
        assert search.status_code == 200
        assert chat_id in [item["id"] for item in search.json()["items"]]

        delete = await client.delete(api_path(f"chats/{chat_id}/username/"), headers=headers)
        assert delete.status_code == 204

        gone = await client.get(api_path("chats/u/kotlinweekly/"), headers=headers)
        assert gone.status_code == 404
        assert gone.json()["error"]["code"] == "NOT_FOUND_CHAT_USERNAME"

    async def test_username_conflict_envelope(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        first = await create_group(client, headers, name="First", is_public=True)
        second = await create_group(client, headers, name="Second", is_public=True)

        assert (await client.put(api_path(f"chats/{first}/username/"), json={"username": "dupe_name"}, headers=headers)).status_code == 200
        conflict = await client.put(api_path(f"chats/{second}/username/"), json={"username": "Dupe_Name"}, headers=headers)

        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "CHAT_USERNAME_TAKEN"

    async def test_invite_link_flow(
        self, client: AsyncClient, user_jwt: UserJWTData, make_user_jwt, create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_group(client, headers, name="Invite only")

        created = await client.post(api_path(f"chats/{chat_id}/invites/"), json={"usage_limit": 2}, headers=headers)
        assert created.status_code == 201, created.text
        invite = created.json()

        listed = await client.get(api_path(f"chats/{chat_id}/invites/"), headers=headers)
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["invites"]] == [invite["id"]]

        guest_headers = create_auth_headers(make_user_jwt(id="50300"))
        preview = await client.get(api_path(f"chats/invites/{invite['code']}/"), headers=guest_headers)
        assert preview.status_code == 200
        assert preview.json()["chat"]["id"] == chat_id
        assert preview.json()["chat"]["is_member"] is False

        joined = await client.post(api_path(f"chats/invites/{invite['code']}/join/"), headers=guest_headers)
        assert joined.status_code == 200, joined.text
        assert joined.json()["status"] == "joined"
        assert joined.json()["chat"]["id"] == chat_id

        again = await client.post(api_path(f"chats/invites/{invite['code']}/join/"), headers=guest_headers)
        assert again.status_code == 409

        revoked = await client.delete(api_path(f"chats/{chat_id}/invites/{invite['id']}/"), headers=headers)
        assert revoked.status_code == 200
        assert revoked.json()["is_revoked"] is True

        late_headers = create_auth_headers(make_user_jwt(id="50301"))
        late = await client.post(api_path(f"chats/invites/{invite['code']}/join/"), headers=late_headers)
        assert late.status_code == 410
        assert late.json()["error"]["code"] == "INVITE_LINK_EXPIRED"
        assert late.json()["error"]["detail"] == {"reason": "revoked"}

    async def test_unknown_invite_code(self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers) -> None:
        response = await client.get(api_path("chats/invites/does-not-exist/"), headers=create_auth_headers(user_jwt))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_INVITE_LINK"

    async def test_avatar_upload_request_and_remove(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_group(client, headers)

        slot = await client.post(
            api_path(f"chats/{chat_id}/avatar/upload-requests/"),
            json={"mime_type": "image/jpeg", "file_size": 1024},
            headers=headers,
        )
        assert slot.status_code == 201, slot.text
        assert slot.json()["upload_url"].startswith("http")

        bad_confirm = await client.post(
            api_path(f"chats/{chat_id}/avatar/upload-requests/confirm/"),
            json={"upload_token": str(uuid4())},
            headers=headers,
        )
        assert bad_confirm.status_code == 400
        assert bad_confirm.json()["error"]["code"] == "INVALID_UPLOAD_TOKEN"

        confirm = await client.post(
            api_path(f"chats/{chat_id}/avatar/upload-requests/confirm/"),
            json={"upload_token": slot.json()["upload_token"]},
            headers=headers,
        )
        assert confirm.status_code == 202

        assert (await client.delete(api_path(f"chats/{chat_id}/avatar/"), headers=headers)).status_code == 204

    async def test_blocked_direct_message_is_refused(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        created = await client.post(api_path("chats/"), json=direct_chat_payload(peer_user_id=OTHER_ID), headers=headers)
        assert created.status_code == 201
        chat_id = created.json()["id"]

        db_session.add(ChatUserBlock(owner_id=int(user_jwt.id), target_id=OTHER_ID))
        await db_session.commit()

        peer_headers = create_auth_headers(make_user_jwt(id=str(OTHER_ID)))
        response = await client.post(
            api_path(f"chats/{chat_id}/messages/"), json=send_text_payload("let me in"), headers=peer_headers,
        )

        assert response.status_code == 403
        body = response.json()["error"]
        assert body["code"] == "USER_BLOCKED"
        assert body["detail"] == {"chat_id": chat_id, "user_id": int(user_jwt.id)}
