import pytest
from httpx import AsyncClient

from app.chats.config import chat_config
from app.core.services.auth.dto import UserJWTData
from tests.chats.integration.factories import group_chat_payload
from tests.support.http import api_path


async def create_chat(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(api_path("chats/"), json=group_chat_payload(name="Media"), headers=headers)
    assert response.status_code == 201
    return str(response.json()["id"])


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestSharedMediaHttp:

    async def test_empty_chat_has_an_empty_tab(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_chat(client, headers)

        response = await client.get(api_path(f"chats/{chat_id}/media/"), params={"type": "photo"}, headers=headers)

        assert response.status_code == 200
        assert response.json() == {"items": [], "has_next": False, "next_cursor": None}

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"type": "gif"},
            {"type": "photo", "limit": 0},
            {"type": "photo", "limit": chat_config.SHARED_MEDIA_MAX_PAGE_SIZE + 1},
            {"type": "photo", "cursor": "abc"},
            {"type": "photo", "cursor": "12:not-a-uuid"},
        ],
    )
    async def test_bad_parameters_are_rejected(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers, params: dict[str, object],
    ) -> None:
        headers = create_auth_headers(user_jwt)
        chat_id = await create_chat(client, headers)

        response = await client.get(api_path(f"chats/{chat_id}/media/"), params=params, headers=headers)

        assert response.status_code == 422

    async def test_outsider_gets_not_a_member(
        self, client: AsyncClient, user_jwt: UserJWTData, make_user_jwt, create_auth_headers,
    ) -> None:
        chat_id = await create_chat(client, create_auth_headers(user_jwt))

        response = await client.get(
            api_path(f"chats/{chat_id}/media/"),
            params={"type": "link"},
            headers=create_auth_headers(make_user_jwt(id="999")),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "NOT_CHAT_MEMBER"
