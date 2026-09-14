import pytest
from dishka import AsyncContainer
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from app.profiles.config import profile_config
from app.profiles.queries.profiles.get_list import GetProfilesQuery, GetProfilesQueryHandler
from app.profiles.schemas.profiles.requests import GetProfilesRequest
from tests.support.http import api_path

VIEWER_ID = 1


def make_query(viewer_id: int = VIEWER_ID, **params) -> GetProfilesQuery:
    request = GetProfilesRequest(**params)
    return GetProfilesQuery(
        request.to_profile_filter(), viewer_id=viewer_id, query=request.q
    )


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestGetProfilesQuery:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> GetProfilesQueryHandler:
        return await request_container.get(GetProfilesQueryHandler)

    async def test_q_finds_a_profile_by_username(
        self,
        handler: GetProfilesQueryHandler,
        make_profile,
    ) -> None:
        await make_profile(8101, "ivan_dev", "Никто")
        await make_profile(8102, "other", "Другой")

        result = await handler.handle(make_query(q="ivan"))

        assert result.total == 1
        assert [profile.id for profile in result.items] == [8101]

    async def test_q_finds_a_profile_by_display_name(
        self,
        handler: GetProfilesQueryHandler,
        make_profile,
    ) -> None:
        await make_profile(8201, "nickname", "Иван Петров")
        await make_profile(8202, "other", "Другой")

        result = await handler.handle(make_query(q="Иван"))

        assert result.total == 1
        assert [profile.id for profile in result.items] == [8201]

    async def test_q_ors_both_fields_in_one_page(
        self,
        handler: GetProfilesQueryHandler,
        make_profile,
    ) -> None:
        await make_profile(8301, "ivan_dev", "Никто")
        await make_profile(8302, "nickname", "Ivan Petrov")
        await make_profile(8303, "other", "Другой")

        result = await handler.handle(make_query(q="ivan"))

        assert result.total == 2
        assert {profile.id for profile in result.items} == {8301, 8302}

    async def test_username_and_display_name_are_still_anded(
        self,
        handler: GetProfilesQueryHandler,
        make_profile,
    ) -> None:
        await make_profile(8401, "ivan_dev", "Иван Петров")
        await make_profile(8402, "ivan_ops", "Другой")

        result = await handler.handle(make_query(username="ivan", display_name="Иван"))

        assert result.total == 1
        assert [profile.id for profile in result.items] == [8401]

    async def test_blocked_users_are_excluded_from_search(
        self,
        handler: GetProfilesQueryHandler,
        make_profile,
        make_block,
    ) -> None:
        await make_profile(8501, "ivan_dev", "Иван Петров")
        await make_profile(8502, "ivan_ops", "Иван Сидоров")
        await make_block(VIEWER_ID, 8502)

        result = await handler.handle(make_query(q="ivan"))

        assert result.total == 1
        assert [profile.id for profile in result.items] == [8501]

    async def test_wildcards_in_q_are_escaped(
        self,
        handler: GetProfilesQueryHandler,
        make_profile,
    ) -> None:
        await make_profile(8601, "ivan_dev", "Иван")

        result = await handler.handle(make_query(q="%v%"))

        assert result.total == 0


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestGetProfilesEndpoint:

    async def test_search_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get(api_path("profiles/"), params={"q": "ivan"})

        assert response.status_code in (401, 403)

    async def test_q_returns_a_page_result(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        make_profile,
    ) -> None:
        await make_profile(8701, "ivan_dev", "Никто")
        await make_profile(8702, "nickname", "Ivan Petrov")

        response = await client.get(
            api_path("profiles/"),
            params={"q": "ivan"},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["page"] == 1
        assert body["page_size"] == 20
        assert {item["id"] for item in body["items"]} == {8701, 8702}

    @pytest.mark.parametrize("conflicting", ["username", "display_name"])
    async def test_q_combined_with_legacy_filters_is_422(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        conflicting: str,
    ) -> None:
        response = await client.get(
            api_path("profiles/"),
            params={"q": "ivan", conflicting: "ivan"},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION"

    @pytest.mark.parametrize("short_q", ["", " ", "i", " i "])
    async def test_too_short_q_is_422(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        short_q: str,
    ) -> None:
        response = await client.get(
            api_path("profiles/"),
            params={"q": short_q},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION"

    async def test_search_is_rate_limited(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        statuses = [
            (
                await client.get(
                    api_path("profiles/"), params={"q": "ivan"}, headers=headers
                )
            ).status_code
            for _ in range(profile_config.PROFILE_SEARCH_RATE_TIMES + 1)
        ]

        assert statuses[:-1] == [200] * profile_config.PROFILE_SEARCH_RATE_TIMES
        assert statuses[-1] == 429
