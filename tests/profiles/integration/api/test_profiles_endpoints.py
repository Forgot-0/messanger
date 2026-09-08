import pytest
from httpx import AsyncClient

from app.core.services.auth.dto import UserJWTData
from app.profiles.config import profile_config
from app.profiles.models.profile import Profile
from app.profiles.tasks import AvatarUploadTask
from tests.support.http import api_path, assert_presigned_url


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestGetOrCreateMyProfile:

    async def test_first_call_creates_the_profile_from_the_token(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        profile_repository,
    ) -> None:
        response = await client.get(
            api_path("profiles/my/"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == int(user_jwt.id)
        assert body["display_name"] is None
        assert body["bio"] is None

        assert await profile_repository.get_by_id(int(user_jwt.id)) is not None

    async def test_second_call_returns_the_same_profile(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        first = await client.get(api_path("profiles/my/"), headers=headers)
        second = await client.get(api_path("profiles/my/"), headers=headers)

        assert first.status_code == second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

    async def test_existing_profile_is_returned_as_is(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persisted_profile: Profile,
    ) -> None:
        response = await client.get(
            api_path("profiles/my/"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 200
        assert response.json()["display_name"] == "test_name"
        assert response.json()["bio"] == "Python Developer"

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get(api_path("profiles/my/"))
        assert response.status_code in (401, 403)

    async def test_new_profile_appears_in_the_public_list(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        before = await client.get(api_path("profiles/"))
        assert before.json()["total"] == 0

        await client.get(api_path("profiles/my/"), headers=create_auth_headers(user_jwt))

        after = await client.get(api_path("profiles/"))
        assert after.json()["total"] == 1


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestGetProfileById:

    async def test_profile_is_returned_with_its_fields(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persisted_profile: Profile,
    ) -> None:
        response = await client.get(
            api_path(f"profiles/{persisted_profile.id}/"),
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["specialization"] == "backend"
        assert set(body["skills"]) == {"python", "sql", "fastapi"}

    async def test_missing_profile_is_404(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        response = await client.get(
            api_path("profiles/999999/"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_PROFILE"

    async def test_someone_elses_profile_is_readable(
        self,
        client: AsyncClient,
        make_user_jwt,
        create_auth_headers,
        persisted_profile: Profile,
    ) -> None:
        stranger = make_user_jwt(id="7301", username="stranger")

        response = await client.get(
            api_path(f"profiles/{persisted_profile.id}/"),
            headers=create_auth_headers(stranger),
        )

        assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestProfilesList:

    async def test_list_is_public(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
    ) -> None:
        response = await client.get(api_path("profiles/"))

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_list_is_paginated(
        self,
        client: AsyncClient,
        db_session,
    ) -> None:
        db_session.add_all([
            Profile.create(
                user_id=7400 + i,
                username=f"pager{i}",
                specialization=None,
                display_name=None,
                bio=None,
                skills=set(),
            )
            for i in range(5)
        ])
        await db_session.commit()

        first = await client.get(api_path("profiles/"), params={"page": 1, "page_size": 2})
        second = await client.get(api_path("profiles/"), params={"page": 2, "page_size": 2})

        assert first.json()["total"] == 5
        assert len(first.json()["items"]) == 2
        ids_first = {p["id"] for p in first.json()["items"]}
        ids_second = {p["id"] for p in second.json()["items"]}
        assert ids_first.isdisjoint(ids_second)

    async def test_page_size_over_the_limit_is_rejected(self, client: AsyncClient) -> None:
        response = await client.get(api_path("profiles/"), params={"page_size": 500})
        assert response.status_code == 422

    async def test_username_filter_narrows_the_list(
        self,
        client: AsyncClient,
        db_session,
    ) -> None:
        db_session.add_all([
            Profile.create(
                user_id=7500, username="findme", specialization=None,
                display_name=None, bio=None, skills=set(),
            ),
            Profile.create(
                user_id=7501, username="other", specialization=None,
                display_name=None, bio=None, skills=set(),
            ),
        ])
        await db_session.commit()

        response = await client.get(api_path("profiles/"), params={"username": "findme"})

        assert response.json()["total"] == 1


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestUpdateProfileEndpoint:

    async def test_owner_updates_own_profile(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persisted_profile: Profile,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        response = await client.put(
            api_path(f"profiles/{persisted_profile.id}/"),
            json={"display_name": "Новое имя", "bio": "Новая био"},
            headers=headers,
        )
        assert response.status_code == 200

        updated = await client.get(
            api_path(f"profiles/{persisted_profile.id}/"), headers=headers
        )
        assert updated.json()["display_name"] == "Новое имя"
        assert updated.json()["bio"] == "Новая био"

    async def test_stranger_cannot_update(
        self,
        client: AsyncClient,
        make_user_jwt,
        create_auth_headers,
        persisted_profile: Profile,
    ) -> None:
        stranger = make_user_jwt(id="7302", username="hijacker")

        response = await client.put(
            api_path(f"profiles/{persisted_profile.id}/"),
            json={"display_name": "Захвачено"},
            headers=create_auth_headers(stranger),
        )

        assert response.status_code == 403

    async def test_admin_can_update_a_foreign_profile(
        self,
        client: AsyncClient,
        super_admin_user_jwt: UserJWTData,
        create_auth_headers,
        persisted_profile: Profile,
    ) -> None:
        response = await client.put(
            api_path(f"profiles/{persisted_profile.id}/"),
            json={"display_name": "Правка админом"},
            headers=create_auth_headers(super_admin_user_jwt),
        )

        assert response.status_code == 200

    async def test_missing_profile_is_404(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        response = await client.put(
            api_path("profiles/999999/"),
            json={"display_name": "x"},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "field,value,expected_code",
        [
            ("bio", "b" * 2000, "TOO_LONG_BIO"),
            ("display_name", "d" * 200, "TOO_LONG_DISPLAY_NAME"),
        ],
    )
    async def test_oversized_text_is_a_domain_error(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persisted_profile: Profile,
        field: str,
        value: str,
        expected_code: str,
    ) -> None:
        response = await client.put(
            api_path(f"profiles/{persisted_profile.id}/"),
            json={field: value},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == expected_code

    async def test_oversized_skill_name_is_rejected(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persisted_profile: Profile,
    ) -> None:
        response = await client.put(
            api_path(f"profiles/{persisted_profile.id}/"),
            json={"skills": ["s" * 100]},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "TOO_LONG_SKILL_NAME"


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestContactEndpoints:

    async def test_owner_adds_a_contact(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persisted_profile: Profile,
    ) -> None:
        headers = create_auth_headers(user_jwt)

        response = await client.post(
            api_path(f"profiles/{persisted_profile.id}/contacts/"),
            json={"provider": "github", "contact": "https://github.com/me"},
            headers=headers,
        )
        assert response.status_code == 200

        profile = await client.get(
            api_path(f"profiles/{persisted_profile.id}/"), headers=headers
        )
        providers = {c["provider"] for c in profile.json()["contacts"]}
        assert "github" in providers

    async def test_stranger_cannot_add_a_contact(
        self,
        client: AsyncClient,
        make_user_jwt,
        create_auth_headers,
        persisted_profile: Profile,
    ) -> None:
        stranger = make_user_jwt(id="7303", username="nosy")

        response = await client.post(
            api_path(f"profiles/{persisted_profile.id}/contacts/"),
            json={"provider": "github", "contact": "https://github.com/evil"},
            headers=create_auth_headers(stranger),
        )

        assert response.status_code == 403

    async def test_owner_removes_a_contact(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persisted_profile_contact,
    ) -> None:
        profile = await persisted_profile_contact([
            ("github", "https://github.com/me"),
            ("telegram", "https://t.me/me"),
        ])
        headers = create_auth_headers(user_jwt)

        response = await client.delete(
            api_path(f"profiles/{profile.id}/github/delete/"), headers=headers
        )
        assert response.status_code == 200

        remaining = await client.get(api_path(f"profiles/{profile.id}/"), headers=headers)
        providers = {c["provider"] for c in remaining.json()["contacts"]}
        assert providers == {"telegram"}

    async def test_removing_a_missing_contact_is_not_an_error(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        persisted_profile: Profile,
    ) -> None:
        response = await client.delete(
            api_path(f"profiles/{persisted_profile.id}/github/delete/"),
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200

    async def test_contact_endpoints_require_authentication(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
    ) -> None:
        response = await client.post(
            api_path(f"profiles/{persisted_profile.id}/contacts/"),
            json={"provider": "github", "contact": "x"},
        )

        assert response.status_code in (401, 403)


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestAvatarEndpoints:

    async def test_presign_returns_a_key_scoped_to_the_user(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        response = await client.post(
            api_path("profiles/avatar/presign/"),
            json={"filename": "avatar.png"},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["file_key"].startswith(f"{user_jwt.id}/")
        assert_presigned_url(
            body["url"],
            bucket=profile_config.PENDING_AVATAR_BUCKET,
            file_key=body["file_key"],
        )

    async def test_presign_sanitises_the_filename(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        response = await client.post(
            api_path("profiles/avatar/presign/"),
            json={"filename": "../../etc/passwd"},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        file_key = response.json()["file_key"]

        prefix, _, rest = file_key.partition("/")
        assert prefix == user_jwt.id
        assert "/" not in rest

    async def test_upload_complete_queues_the_resize_task(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        mock_queue_service,
    ) -> None:

        response = await client.post(
            api_path("profiles/avatar/upload_complete/"),
            json={"file_key": f"{user_jwt.id}/avatar.png"},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        assert len(mock_queue_service.pushed) == 1
        task, data = mock_queue_service.pushed[0]
        assert task is AvatarUploadTask
        assert data == {
            "user_id": int(user_jwt.id),
            "key_base": f"{user_jwt.id}/avatar.png",
        }

    async def test_presign_is_rate_limited(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        headers = create_auth_headers(user_jwt)
        payload = {"filename": "avatar.png"}

        statuses = [
            (await client.post(
                api_path("profiles/avatar/presign/"), json=payload, headers=headers
            )).status_code
            for _ in range(5)
        ]

        assert statuses[:4] == [200, 200, 200, 200]
        assert statuses[4] == 429

    async def test_avatar_endpoints_require_authentication(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            api_path("profiles/avatar/presign/"), json={"filename": "a.png"}
        )
        assert response.status_code in (401, 403)
