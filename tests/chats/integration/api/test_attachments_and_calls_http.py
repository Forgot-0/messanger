from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import group_chat_payload, send_text_payload
from tests.support.http import api_path


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestAttachmentsHttpEndpoints:
    async def test_request_upload_slots_returns_presigned_urls(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Attachments"),
            headers=headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        response = await client.post(
            api_path(f"chats/{chat_id}/attachments/upload-requests/"),
            json={
                "uploads": [
                    {"filename": "photo.jpg", "mime_type": "image/jpeg", "file_size": 1024},
                ]
            },
            headers=headers,
        )
        assert response.status_code == 201
        slots = response.json()
        assert len(slots) == 1
        assert "upload_token" in slots[0]
        assert slots[0]["upload_url"].startswith("https://storage.test/upload/")

    async def test_confirm_upload_accepted(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Confirm upload"),
            headers=headers,
        )
        chat_id = create.json()["id"]

        slots_resp = await client.post(
            api_path(f"chats/{chat_id}/attachments/upload-requests/"),
            json={
                "uploads": [
                    {"filename": "doc.pdf", "mime_type": "application/pdf", "file_size": 2048},
                ]
            },
            headers=headers,
        )
        token = slots_resp.json()[0]["upload_token"]

        confirm = await client.post(
            api_path(f"chats/{chat_id}/attachments/upload-requests/confirm/"),
            json={"upload_tokens": [token]},
            headers=headers,
        )
        assert confirm.status_code == 202

    async def test_download_url_not_found_for_random_attachment(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Download url"),
            headers=headers,
        )
        chat_id = create.json()["id"]

        msg = await client.post(
            api_path(f"chats/{chat_id}/messages/"),
            json=send_text_payload("with fake attachment ref"),
            headers=headers,
        )
        assert msg.status_code == 201
        message_id = msg.json()["id"]
        fake_attachment = uuid4()

        response = await client.get(
            api_path(
                f"chats/{chat_id}/messages/{message_id}/attachments/{fake_attachment}/download-url/"
            ),
            headers=headers,
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ATTACHMENT_NOT_FOUND"


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestCallsHttpEndpoints:
    async def test_join_call_returns_token(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Calls"),
            headers=headers,
        )
        chat_id = create.json()["id"]

        response = await client.post(api_path(f"chats/{chat_id}/calls/join/"), headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["token"] == "integration-test-livekit-jwt"
        assert data["slug"] == chat_id
        assert "livekit_url" in data

    async def test_join_call_forbidden_for_non_member(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        owner_headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Calls closed"),
            headers=owner_headers,
        )
        assert create.status_code == 201
        chat_id = create.json()["id"]

        stranger = make_user_jwt(id="50300", username="nocalluser")
        response = await client.post(
            api_path(f"chats/{chat_id}/calls/join/"),
            headers=create_auth_headers(stranger),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "NOT_CHAT_MEMBER"

    async def test_mute_participant_no_op_with_stub_livekit(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        create = await client.post(
            api_path("chats/"),
            json=group_chat_payload(name="Mute call", member_ids=[1, 50_200]),
            headers=headers,
        )
        chat_id = create.json()["id"]

        response = await client.post(
            api_path(f"chats/{chat_id}/calls/participants/50200/mute/"),
            json={"muted": True},
            headers=headers,
        )
        assert response.status_code == 204
