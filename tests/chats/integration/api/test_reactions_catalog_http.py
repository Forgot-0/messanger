import pytest
from httpx import AsyncClient

from app.chats.config import chat_config
from app.core.services.auth.dto import UserJWTData
from tests.support.http import api_path

CATALOG_PATH = api_path("chats/reactions/catalog/")


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestReactionsCatalog:

    async def test_returns_catalog_from_config(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        response = await client.get(CATALOG_PATH, headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        # Сверяемся с конфигом, а не с переписанным руками списком: каталог
        # переопределяется через .env и на каждом стенде свой.
        assert body["emojis"] == list(chat_config.DEFAULT_REACTIONS)
        assert len(body["emojis"]) == len(set(body["emojis"]))
        assert body["max_reactions_per_user_per_message"] == chat_config.MAX_REACTIONS_PER_USER_PER_MESSAGE
        assert body["max_distinct_reactions_per_message"] == chat_config.MAX_DISTINCT_REACTIONS_PER_MESSAGE
        assert body["max_reaction_length"] == chat_config.MAX_REACTION_LENGTH
        assert body["version"]

    async def test_static_path_is_not_eaten_by_chat_id_route(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        response = await client.get(CATALOG_PATH, headers=headers)

        # 422 означало бы, что путь уехал в /{chat_id}/ и "reactions" пробуют
        # разобрать как UUID.
        assert response.status_code == 200, response.text

    async def test_requires_authorization(self, client: AsyncClient) -> None:
        response = await client.get(CATALOG_PATH)

        assert response.status_code == 403, response.text

    async def test_sends_cache_headers(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        response = await client.get(CATALOG_PATH, headers=headers)

        assert response.headers["etag"] == f'"{response.json()["version"]}"'
        assert f"max-age={chat_config.REACTIONS_CATALOG_CACHE_TTL}" in response.headers["cache-control"]

    async def test_repeated_request_with_if_none_match_gives_304(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        first = await client.get(CATALOG_PATH, headers=headers)
        assert first.status_code == 200, first.text
        etag = first.headers["etag"]

        second = await client.get(
            CATALOG_PATH, headers={**headers, "If-None-Match": etag}
        )

        assert second.status_code == 304
        assert second.headers["etag"] == etag
        assert not second.content

    async def test_stale_if_none_match_gives_200(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        response = await client.get(
            CATALOG_PATH, headers={**headers, "If-None-Match": '"deadbeefdeadbeef"'}
        )

        assert response.status_code == 200, response.text
        assert response.json()["emojis"] == list(chat_config.DEFAULT_REACTIONS)

    async def test_config_override_changes_body_and_version(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        before = await client.get(CATALOG_PATH, headers=headers)
        assert before.status_code == 200, before.text

        monkeypatch.setattr(chat_config, "DEFAULT_REACTIONS", ("👍", "🔥"))

        after = await client.get(CATALOG_PATH, headers=headers)

        assert after.status_code == 200, after.text
        assert after.json()["emojis"] == ["👍", "🔥"]
        assert after.json()["version"] != before.json()["version"]

        # Старый ETag после подмены каталога больше не валиден.
        stale = await client.get(
            CATALOG_PATH, headers={**headers, "If-None-Match": before.headers["etag"]}
        )
        assert stale.status_code == 200, stale.text
