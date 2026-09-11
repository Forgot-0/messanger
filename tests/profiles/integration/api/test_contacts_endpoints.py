import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from app.profiles.config import profile_config
from app.profiles.tasks import ContactsImportTask
from tests.support.http import api_path

OWNER_ID = 1
FRIEND_ID = 8801


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestContactsCrudEndpoints:

    async def test_contact_is_added_and_listed(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        make_profile,
    ) -> None:
        await make_profile(FRIEND_ID, "friend", "Friend")
        headers = create_auth_headers(user_jwt)

        created = await client.post(
            api_path("contacts/"),
            json={"user_id": FRIEND_ID, "first_name": "Вася"},
            headers=headers,
        )
        assert created.status_code == 201
        assert created.json()["contact_id"] == FRIEND_ID

        listed = await client.get(api_path("contacts/"), headers=headers)
        assert listed.status_code == 200
        body = listed.json()
        assert body["has_next"] is False
        assert body["contacts"][0]["first_name"] == "Вася"
        assert body["contacts"][0]["profile"]["id"] == FRIEND_ID
        assert body["contacts"][0]["profile"]["display_name"] == "Friend"

    async def test_contact_can_be_added_by_username(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        make_profile,
    ) -> None:
        await make_profile(FRIEND_ID, "friend")

        response = await client.post(
            api_path("contacts/"),
            json={"username": "friend"},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 201

    async def test_request_without_a_target_is_rejected(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.post(
            api_path("contacts/"), json={}, headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 422

    async def test_unknown_target_is_404(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.post(
            api_path("contacts/"),
            json={"user_id": 999999},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_CONTACT_TARGET"

    async def test_local_name_is_patched(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        make_contact,
    ) -> None:
        await make_contact(OWNER_ID, FRIEND_ID)

        response = await client.patch(
            api_path(f"contacts/{FRIEND_ID}/"),
            json={"first_name": "Петя", "is_favorite": True},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        assert response.json()["first_name"] == "Петя"
        assert response.json()["is_favorite"] is True

    async def test_contact_is_deleted(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        make_contact,
    ) -> None:
        await make_contact(OWNER_ID, FRIEND_ID)
        headers = create_auth_headers(user_jwt)

        deleted = await client.delete(api_path(f"contacts/{FRIEND_ID}/"), headers=headers)
        assert deleted.status_code == 204

        listed = await client.get(api_path("contacts/"), headers=headers)
        assert listed.json()["contacts"] == []

    async def test_deleting_a_missing_contact_is_404(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.delete(
            api_path(f"contacts/{FRIEND_ID}/"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_CONTACT"

    async def test_path_without_trailing_slash_is_404(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.get(
            api_path("contacts"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 404

    async def test_endpoints_require_authentication(self, client: AsyncClient) -> None:
        response = await client.get(api_path("contacts/"))

        assert response.status_code in (401, 403)


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestBlockEndpoints:

    async def test_blocked_route_is_not_swallowed_by_the_id_route(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        make_profile,
        make_block,
    ) -> None:
        await make_profile(FRIEND_ID, "blocked_one", "Blocked")
        await make_block(OWNER_ID, FRIEND_ID)

        response = await client.get(
            api_path("contacts/blocked/"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 200
        assert response.json()["blocked"][0]["target_id"] == FRIEND_ID

    async def test_block_and_unblock_round_trip(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        blocked = await client.post(api_path(f"contacts/{FRIEND_ID}/block/"), headers=headers)
        assert blocked.status_code == 204

        listed = await client.get(api_path("contacts/blocked/"), headers=headers)
        assert [b["target_id"] for b in listed.json()["blocked"]] == [FRIEND_ID]

        unblocked = await client.delete(
            api_path(f"contacts/{FRIEND_ID}/block/"), headers=headers
        )
        assert unblocked.status_code == 204

        empty = await client.get(api_path("contacts/blocked/"), headers=headers)
        assert empty.json()["blocked"] == []

    async def test_blocking_yourself_is_400(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.post(
            api_path(f"contacts/{user_jwt.id}/block/"),
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "SELF_CONTACT_NOT_ALLOWED"


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestSearchEndpoint:

    async def test_search_route_is_not_swallowed_by_the_id_route(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        make_profile,
    ) -> None:
        await make_profile(FRIEND_ID, "searchme", "Search Me")

        response = await client.get(
            api_path("contacts/search/"),
            params={"query": "@searchme"},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["user_id"] == FRIEND_ID
        assert item["profile"]["id"] == FRIEND_ID
        assert item["contact"] is None

    async def test_empty_query_is_rejected(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.get(
            api_path("contacts/search/"),
            params={"query": ""},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestImportEndpoint:

    async def test_small_batch_is_imported_inline(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        make_profile,
        register_identifier,
    ) -> None:
        await make_profile(FRIEND_ID, "friend")
        await register_identifier(FRIEND_ID, "friend@example.com")

        response = await client.post(
            api_path("contacts/import/"),
            json={"contacts": [{"email": "friend@example.com", "first_name": "Вася"}]},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "done"
        assert body["matched"] == 1
        assert body["contacts"][0]["contact_id"] == FRIEND_ID

    async def test_large_batch_is_queued_with_202(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        mock_queue_service,
    ) -> None:
        contacts = [
            {"email": f"user{i}@example.com"}
            for i in range(profile_config.CONTACTS_IMPORT_SYNC_THRESHOLD + 1)
        ]

        response = await client.post(
            api_path("contacts/import/"),
            json={"contacts": contacts},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        assert response.json()["accepted"] == len(contacts)

        task, data = mock_queue_service.pushed[-1]
        assert task is ContactsImportTask
        assert data["owner_id"] == int(user_jwt.id)
        assert len(data["entries"]) == len(contacts)

    async def test_batch_over_the_hard_limit_is_422(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        contacts = [
            {"email": f"user{i}@example.com"}
            for i in range(profile_config.CONTACTS_IMPORT_MAX_BATCH + 1)
        ]

        response = await client.post(
            api_path("contacts/import/"),
            json={"contacts": contacts},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 422

    async def test_repeated_idempotency_key_returns_the_first_result(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        make_profile,
        register_identifier,
    ) -> None:
        await make_profile(FRIEND_ID, "friend")
        await register_identifier(FRIEND_ID, "friend@example.com")
        headers = create_auth_headers(user_jwt) | {"Idempotency-Key": "import-1"}
        payload = {"contacts": [{"email": "friend@example.com"}]}

        first = await client.post(api_path("contacts/import/"), json=payload, headers=headers)
        second = await client.post(api_path("contacts/import/"), json=payload, headers=headers)

        assert first.json() == second.json()

    async def test_import_is_rate_limited(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        payload = {"contacts": [{"email": "somebody@example.com"}]}

        statuses = [
            (
                await client.post(api_path("contacts/import/"), json=payload, headers=headers)
            ).status_code
            for _ in range(profile_config.CONTACTS_IMPORT_RATE_TIMES + 1)
        ]

        assert statuses[-1] == 429
