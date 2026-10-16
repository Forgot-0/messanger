import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox.model import OutboxMessage
from app.core.privacy import PrivacyRule, PrivacyVisibility
from app.core.services.auth.dto import UserJWTData
from app.profiles.config import profile_config
from app.profiles.models.privacy import PrivacyUpdated
from tests.support.http import api_path


@pytest.mark.integration
@pytest.mark.profiles
@pytest.mark.asyncio
class TestPrivacyEndpoints:

    async def test_defaults_are_returned_without_a_row(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.get(
            api_path("profiles/privacy/"), headers=create_auth_headers(user_jwt)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["rules"] == {rule.value: "everybody" for rule in PrivacyRule}
        assert body["exceptions"]["photo"] == {"allow": [], "deny": []}

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get(api_path("profiles/privacy/"))).status_code in (401, 403)
        assert (
            await client.put(api_path("profiles/privacy/"), json={"rules": {"photo": "nobody"}})
        ).status_code in (401, 403)

    async def test_partial_update_keeps_other_rules(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        headers = create_auth_headers(user_jwt)

        first = await client.put(
            api_path("profiles/privacy/"), json={"rules": {"photo": "contacts"}}, headers=headers
        )
        assert first.status_code == 200
        assert first.json()["rules"]["photo"] == "contacts"

        second = await client.put(
            api_path("profiles/privacy/"), json={"rules": {"calls": "nobody"}}, headers=headers
        )
        assert second.status_code == 200
        assert second.json()["rules"] == {
            "last_seen": "everybody",
            "photo": "contacts",
            "messages": "everybody",
            "group_invites": "everybody",
            "calls": "nobody",
        }

    async def test_exceptions_are_replaced_per_rule(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        headers = create_auth_headers(user_jwt)

        await client.put(
            api_path("profiles/privacy/"),
            json={"exceptions": {"photo": {"allow": [5, 6], "deny": [7]}}},
            headers=headers,
        )
        replaced = await client.put(
            api_path("profiles/privacy/"),
            json={"exceptions": {"photo": {"allow": [8], "deny": []}}},
            headers=headers,
        )

        assert replaced.status_code == 200
        assert replaced.json()["exceptions"]["photo"] == {"allow": [8], "deny": []}

        stored = await client.get(api_path("profiles/privacy/"), headers=headers)
        assert stored.json()["exceptions"]["photo"] == {"allow": [8], "deny": []}
        assert stored.json()["exceptions"]["calls"] == {"allow": [], "deny": []}

    async def test_own_id_and_duplicates_are_dropped(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.put(
            api_path("profiles/privacy/"),
            json={
                "exceptions": {
                    "messages": {"allow": [int(user_jwt.id), 10], "deny": [10, 11]}
                }
            },
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 200
        # «Можно» сильнее «нельзя», себя в исключениях не держим
        assert response.json()["exceptions"]["messages"] == {"allow": [10], "deny": [11]}

    async def test_too_many_exceptions_are_refused(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        limit = profile_config.MAX_PRIVACY_EXCEPTIONS_PER_RULE
        response = await client.put(
            api_path("profiles/privacy/"),
            json={
                "exceptions": {
                    "photo": {
                        "allow": list(range(1000, 1000 + limit)),
                        "deny": list(range(5000, 5000 + limit)),
                    }
                }
            },
            headers=create_auth_headers(user_jwt),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "PRIVACY_EXCEPTIONS_LIMIT"

    async def test_empty_body_is_rejected(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.put(
            api_path("profiles/privacy/"), json={}, headers=create_auth_headers(user_jwt)
        )
        assert response.status_code == 422

    async def test_unknown_visibility_is_rejected(
        self, client: AsyncClient, user_jwt: UserJWTData, create_auth_headers
    ) -> None:
        response = await client.put(
            api_path("profiles/privacy/"),
            json={"rules": {"photo": "friends-of-friends"}},
            headers=create_auth_headers(user_jwt),
        )
        assert response.status_code == 422

    async def test_update_goes_through_the_outbox(
        self,
        client: AsyncClient,
        user_jwt: UserJWTData,
        create_auth_headers,
        db_session: AsyncSession,
    ) -> None:
        await client.put(
            api_path("profiles/privacy/"),
            json={
                "rules": {"photo": PrivacyVisibility.CONTACTS.value},
                "exceptions": {"photo": {"allow": [12], "deny": []}},
            },
            headers=create_auth_headers(user_jwt),
        )

        result = await db_session.execute(
            select(OutboxMessage).where(
                OutboxMessage.event_name == PrivacyUpdated.__event_name__,
                OutboxMessage.aggregate_id == user_jwt.id,
            )
        )
        messages = list(result.scalars().all())

        assert len(messages) == 1
        assert messages[0].topic == "profiles"
        assert messages[0].payload["rules"]["photo"] == "contacts"
        assert messages[0].payload["exceptions"]["photo"] == {"allow": [12], "deny": []}
