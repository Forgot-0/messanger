import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.utils import PrivacyRule, PrivacyVisibility
from app.core.services.auth.dto import UserJWTData
from app.profiles.config import profile_config
from app.profiles.models.privacy import ProfilePrivacy, ProfilePrivacyException
from app.profiles.models.profile import Profile
from tests.support.http import api_path, assert_presigned_url

OWNER_ID = 4200
OWNER_USERNAME = "shy_owner"


@pytest.fixture
async def owner_with_photo(db_session: AsyncSession, make_profile) -> Profile:
    profile = await make_profile(OWNER_ID, OWNER_USERNAME, "Shy Owner")
    profile.avatars = {"64": {"jpg": f"{OWNER_ID}/64.jpg"}}
    await db_session.commit()
    return profile


@pytest.fixture
def set_privacy(db_session: AsyncSession):
    async def _set(
        user_id: int,
        *,
        exceptions: list[tuple[PrivacyRule, int, bool]] | None = None,
        **rules: PrivacyVisibility,
    ) -> None:
        privacy = await db_session.get(ProfilePrivacy, user_id)
        if privacy is None:
            privacy = ProfilePrivacy.create(user_id)
            db_session.add(privacy)

        for rule, visibility in rules.items():
            privacy.set_rule(PrivacyRule(rule), visibility)

        for rule, target_id, allow in exceptions or []:
            db_session.add(
                ProfilePrivacyException(
                    owner_id=user_id, rule=rule, target_id=target_id, allow=allow
                )
            )

        privacy.pull_events()
        await db_session.commit()

    return _set


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestProfilePhotoPrivacy:

    async def test_stranger_gets_no_photo_when_nobody(
        self,
        client: AsyncClient,
        owner_with_photo: Profile,
        set_privacy,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        await set_privacy(OWNER_ID, photo=PrivacyVisibility.NOBODY)

        response = await client.get(
            api_path(f"profiles/{OWNER_ID}/"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 200
        assert response.json()["avatars"] == {}
        assert response.json()["username"] == OWNER_USERNAME

    async def test_owner_still_sees_own_photo(
        self,
        client: AsyncClient,
        owner_with_photo: Profile,
        set_privacy,
        make_user_jwt,
        create_auth_headers,
    ) -> None:
        await set_privacy(OWNER_ID, photo=PrivacyVisibility.NOBODY)

        response = await client.get(
            api_path(f"profiles/{OWNER_ID}/"),
            headers=create_auth_headers(make_user_jwt(id=str(OWNER_ID))),
        )

        assert_presigned_url(
            response.json()["avatars"]["64"]["jpg"],
            bucket=profile_config.AVATAR_BUCKET,
            file_key=f"{OWNER_ID}/64.jpg",
        )

    async def test_contacts_only_shows_it_to_a_contact(
        self,
        client: AsyncClient,
        owner_with_photo: Profile,
        set_privacy,
        make_contact,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        await set_privacy(OWNER_ID, photo=PrivacyVisibility.CONTACTS)
        headers = create_auth_headers(user_jwt)

        hidden = await client.get(api_path(f"profiles/{OWNER_ID}/"), headers=headers)
        assert hidden.json()["avatars"] == {}

        # Контакт определяет владелец настройки: он держит смотрящего в своей книге
        await make_contact(owner_id=OWNER_ID, contact_id=int(user_jwt.id))
        visible = await client.get(api_path(f"profiles/{OWNER_ID}/"), headers=headers)
        assert visible.json()["avatars"]["64"]["jpg"].startswith("http")

    async def test_deny_exception_hides_an_open_photo(
        self,
        client: AsyncClient,
        owner_with_photo: Profile,
        set_privacy,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        await set_privacy(
            OWNER_ID,
            photo=PrivacyVisibility.EVERYBODY,
            exceptions=[(PrivacyRule.PHOTO, int(user_jwt.id), False)],
        )

        response = await client.get(
            api_path(f"profiles/{OWNER_ID}/"), headers=create_auth_headers(user_jwt)
        )
        assert response.json()["avatars"] == {}

    async def test_allow_exception_shows_a_closed_photo(
        self,
        client: AsyncClient,
        owner_with_photo: Profile,
        set_privacy,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        await set_privacy(
            OWNER_ID,
            photo=PrivacyVisibility.NOBODY,
            exceptions=[(PrivacyRule.PHOTO, int(user_jwt.id), True)],
        )

        response = await client.get(
            api_path(f"profiles/{OWNER_ID}/"), headers=create_auth_headers(user_jwt)
        )
        assert response.json()["avatars"]["64"]["jpg"].startswith("http")

    async def test_list_hides_the_photo_too(
        self,
        client: AsyncClient,
        owner_with_photo: Profile,
        set_privacy,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        await set_privacy(OWNER_ID, photo=PrivacyVisibility.NOBODY)

        response = await client.get(
            api_path("profiles/"),
            params={"username": OWNER_USERNAME},
            headers=create_auth_headers(user_jwt),
        )

        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["avatars"] == {}

    async def test_contacts_list_hides_the_photo(
        self,
        client: AsyncClient,
        owner_with_photo: Profile,
        set_privacy,
        make_contact,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        """Контакт в моей книге ещё не значит, что я в его книге."""
        await set_privacy(OWNER_ID, photo=PrivacyVisibility.CONTACTS)
        await make_contact(owner_id=int(user_jwt.id), contact_id=OWNER_ID)

        response = await client.get(
            api_path("contacts/"), headers=create_auth_headers(user_jwt)
        )

        contacts = response.json()["contacts"]
        assert len(contacts) == 1
        assert contacts[0]["profile"]["avatars"] == {}


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestPublicUsernameRoutePrivacy:
    """`GET /profiles/u/{username}/` остаётся публичным — но без фото, если нельзя."""

    async def test_anonymous_sees_an_open_photo(
        self, client: AsyncClient, owner_with_photo: Profile
    ) -> None:
        response = await client.get(api_path(f"profiles/u/{OWNER_USERNAME}/"))

        assert response.status_code == 200
        assert_presigned_url(
            response.json()["avatars"]["64"]["jpg"],
            bucket=profile_config.AVATAR_BUCKET,
            file_key=f"{OWNER_ID}/64.jpg",
        )

    async def test_anonymous_gets_the_profile_without_a_private_photo(
        self, client: AsyncClient, owner_with_photo: Profile, set_privacy
    ) -> None:
        await set_privacy(OWNER_ID, photo=PrivacyVisibility.CONTACTS)

        response = await client.get(api_path(f"profiles/u/{OWNER_USERNAME}/"))

        assert response.status_code == 200
        body = response.json()
        assert body["username"] == OWNER_USERNAME
        assert body["display_name"] == "Shy Owner"
        assert body["avatars"] == {}

    async def test_token_on_the_public_route_applies_the_rule(
        self,
        client: AsyncClient,
        owner_with_photo: Profile,
        set_privacy,
        make_contact,
        user_jwt: UserJWTData,
        create_auth_headers,
    ) -> None:
        await set_privacy(OWNER_ID, photo=PrivacyVisibility.CONTACTS)
        await make_contact(owner_id=OWNER_ID, contact_id=int(user_jwt.id))

        response = await client.get(
            api_path(f"profiles/u/{OWNER_USERNAME}/"), headers=create_auth_headers(user_jwt)
        )

        assert response.json()["avatars"]["64"]["jpg"].startswith("http")
