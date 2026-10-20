from uuid import uuid7

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.utils import PrivacyRule, PrivacyVisibility
from app.core.services.auth.dto import UserJWTData
from app.profiles.config import profile_config
from app.profiles.models.privacy import ProfilePrivacy
from app.profiles.models.profile import Profile
from tests.support.http import api_path, assert_presigned_url

VIEWER_ID = 4300


@pytest.fixture
async def history(persisted_profile: Profile, make_photo):
    """Три фото, текущее — самое свежее."""
    oldest = await make_photo(persisted_profile, age=20)
    middle = await make_photo(persisted_profile, age=10)
    main = await make_photo(persisted_profile, main=True)
    return main, middle, oldest


@pytest.fixture
def viewer(make_user_jwt) -> UserJWTData:
    return make_user_jwt(id=str(VIEWER_ID), username="viewer")


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestProfilePhotosList:

    async def test_owner_browses_the_history_main_first(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
        history,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        main, middle, oldest = history

        response = await client.get(
            api_path(f"profiles/{persisted_profile.id}/photos/"),
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert [item["id"] for item in body["items"]] == [str(main.id), str(middle.id), str(oldest.id)]
        assert [item["is_main"] for item in body["items"]] == [True, False, False]
        assert_presigned_url(
            body["items"][1]["avatars"]["64"]["jpg"],
            bucket=profile_config.AVATAR_BUCKET,
            file_key=middle.avatars[64]["jpg"],
        )

    async def test_history_is_paginated(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
        history,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        _, middle, oldest = history

        response = await client.get(
            api_path(f"profiles/{persisted_profile.id}/photos/"),
            params={"page": 2, "page_size": 2},
            headers=create_auth_headers(user_jwt),
        )

        body = response.json()
        assert body["total"] == 3 and body["page"] == 2
        assert [item["id"] for item in body["items"]] == [str(oldest.id)]

    async def test_stranger_sees_an_open_history(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
        history,
        viewer: UserJWTData,
        create_auth_headers,
    ) -> None:
        response = await client.get(
            api_path(f"profiles/{persisted_profile.id}/photos/"),
            headers=create_auth_headers(viewer),
        )

        assert response.json()["total"] == 3

    async def test_photo_privacy_hides_the_whole_history(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
        history,
        viewer: UserJWTData,
        create_auth_headers,
        db_session: AsyncSession,
    ) -> None:
        privacy = ProfilePrivacy.create(persisted_profile.id)
        privacy.set_rule(PrivacyRule.PHOTO, PrivacyVisibility.NOBODY)
        privacy.pull_events()
        db_session.add(privacy)
        await db_session.commit()

        response = await client.get(
            api_path(f"profiles/{persisted_profile.id}/photos/"),
            headers=create_auth_headers(viewer),
        )

        assert response.status_code == 200
        assert response.json()["items"] == [] and response.json()["total"] == 0

    async def test_blocked_viewer_gets_nothing(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
        history,
        viewer: UserJWTData,
        create_auth_headers,
        make_block,
    ) -> None:
        await make_block(persisted_profile.id, VIEWER_ID)

        response = await client.get(
            api_path(f"profiles/{persisted_profile.id}/photos/"),
            headers=create_auth_headers(viewer),
        )

        assert response.json()["total"] == 0

    async def test_unknown_profile_is_404(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.get(
            api_path("profiles/999999/photos/"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_PROFILE"

    async def test_requires_authentication(
        self, client: AsyncClient, persisted_profile: Profile
    ) -> None:
        response = await client.get(api_path(f"profiles/{persisted_profile.id}/photos/"))

        assert response.status_code in (401, 403)


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestProfilePhotoWrites:

    async def test_set_main_then_delete_through_the_api(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
        history,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        main, middle, oldest = history
        headers = create_auth_headers(user_jwt)

        promoted = await client.put(api_path(f"profiles/photos/{oldest.id}/main/"), headers=headers)
        assert promoted.status_code == 204

        removed = await client.delete(api_path(f"profiles/photos/{main.id}/"), headers=headers)
        assert removed.status_code == 204

        listed = (await client.get(api_path(f"profiles/{persisted_profile.id}/photos/"), headers=headers)).json()
        assert [item["id"] for item in listed["items"]] == [str(oldest.id), str(middle.id)]
        assert listed["items"][0]["is_main"] is True

        profile = (await client.get(api_path(f"profiles/{persisted_profile.id}/"), headers=headers)).json()
        assert_presigned_url(
            profile["avatars"]["64"]["jpg"],
            bucket=profile_config.AVATAR_BUCKET,
            file_key=oldest.avatars[64]["jpg"],
        )

    async def test_delete_avatar_drops_the_current_photo(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
        history,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        _, middle, _ = history
        headers = create_auth_headers(user_jwt)

        response = await client.delete(api_path("profiles/avatar/"), headers=headers)

        assert response.status_code == 204
        listed = (await client.get(api_path(f"profiles/{persisted_profile.id}/photos/"), headers=headers)).json()
        assert listed["total"] == 2
        assert listed["items"][0]["id"] == str(middle.id) and listed["items"][0]["is_main"] is True

    async def test_unknown_photo_is_404(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        response = await client.delete(
            api_path(f"profiles/photos/{uuid7()}/"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND_PROFILE_PHOTO"

    async def test_presign_is_refused_when_the_history_is_full(
        self,
        client: AsyncClient,
        persisted_profile: Profile,
        history,
        user_jwt: UserJWTData,
        create_auth_headers,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(profile_config, "MAX_PROFILE_PHOTOS", 3)

        response = await client.post(
            api_path("profiles/avatar/presign/"),
            json={"filename": "avatar.jpg"},
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "PROFILE_PHOTOS_LIMIT",
            "message": "Profile photos limit reached, delete an old photo first",
            "detail": {"limit": 3},
        }
