import pytest
from httpx import AsyncClient

from app.auth.models.user import User
from tests.support.http import api_path


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestChangeUsernameEndpoint:

    async def test_owner_changes_the_username(
        self,
        client: AsyncClient,
        standard_user: User,
        auth_headers,
    ) -> None:
        response = await client.put(
            api_path("users/me/username/"),
            json={"username": "new_handle"},
            headers=auth_headers(standard_user),
        )

        assert response.status_code == 200
        assert response.json() == {
            "id": standard_user.id,
            "username": "new_handle",
            "email": standard_user.email,
        }

    async def test_new_name_is_what_me_returns_and_what_logs_in(
        self,
        client: AsyncClient,
        standard_user: User,
        auth_headers,
    ) -> None:
        headers = auth_headers(standard_user)
        await client.put(api_path("users/me/username/"), json={"username": "new_handle"}, headers=headers)

        me = await client.get(api_path("users/me/"), headers=headers)
        assert me.status_code == 200
        assert me.json()["username"] == "new_handle"

        new_login = await client.post(
            api_path("auth/login/"), data={"username": "new_handle", "password": "TestPass123!"}
        )
        old_login = await client.post(
            api_path("auth/login/"), data={"username": "standarduser", "password": "TestPass123!"}
        )
        assert new_login.status_code == 200
        assert old_login.status_code == 400

    async def test_taken_name_is_409(
        self,
        client: AsyncClient,
        standard_user: User,
        admin_user: User,
        auth_headers,
    ) -> None:
        response = await client.put(
            api_path("users/me/username/"),
            json={"username": "ADMINUSER"},
            headers=auth_headers(standard_user),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "USERNAME_TAKEN"

    @pytest.mark.parametrize(
        "username, reason",
        [("abcd", "length"), ("ivan.petrov", "format"), ("support", "reserved")],
    )
    async def test_rule_violation_is_400_with_a_reason(
        self,
        client: AsyncClient,
        standard_user: User,
        auth_headers,
        username: str,
        reason: str,
    ) -> None:
        response = await client.put(
            api_path("users/me/username/"),
            json={"username": username},
            headers=auth_headers(standard_user),
        )

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "INVALID_USERNAME"
        assert error["detail"] == {"username": username, "reason": reason}

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.put(api_path("users/me/username/"), json={"username": "new_handle"})

        assert response.status_code in (401, 403)


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestCheckUsernameEndpoint:

    async def check(self, client: AsyncClient, headers: dict[str, str], username: str) -> dict:
        response = await client.get(
            api_path("users/username/check/"), params={"username": username}, headers=headers
        )
        assert response.status_code == 200
        return response.json()

    async def test_free_name_is_available(
        self, client: AsyncClient, standard_user: User, auth_headers
    ) -> None:
        body = await self.check(client, auth_headers(standard_user), "@free_name")

        assert body == {"username": "free_name", "available": True, "reason": None}

    async def test_name_of_another_user_is_taken_in_any_case(
        self, client: AsyncClient, standard_user: User, admin_user: User, auth_headers
    ) -> None:
        body = await self.check(client, auth_headers(standard_user), "AdminUser")

        assert body == {"username": "AdminUser", "available": False, "reason": "taken"}

    async def test_own_name_is_available(
        self, client: AsyncClient, standard_user: User, auth_headers
    ) -> None:
        body = await self.check(client, auth_headers(standard_user), "StandardUser")

        assert body["available"] is True

    @pytest.mark.parametrize(
        "username, reason",
        [("abc", "length"), ("_ivan_", "format"), ("Admin", "reserved")],
    )
    async def test_rule_violation_is_reported_not_raised(
        self, client: AsyncClient, standard_user: User, auth_headers, username: str, reason: str
    ) -> None:
        body = await self.check(client, auth_headers(standard_user), username)

        assert body == {"username": username, "available": False, "reason": reason}


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestRegistrationUsernameRules:

    async def register(self, client: AsyncClient, username: str):
        return await client.post(
            api_path("users/register/"),
            json={
                "username": username,
                "email": f"{username.replace(' ', '')}@example.com",
                "password": "TestPass123!",
                "password_repeat": "TestPass123!",
            },
        )

    async def test_reserved_name_cannot_be_registered(self, client: AsyncClient) -> None:
        response = await self.register(client, "Admin")

        assert response.status_code == 400
        assert response.json()["error"]["detail"] == {"username": "Admin", "reason": "reserved"}

    async def test_name_differing_only_in_case_is_a_duplicate(
        self, client: AsyncClient, standard_user: User
    ) -> None:
        response = await self.register(client, "StandardUser")

        assert response.status_code == 409
        assert response.json()["error"]["detail"] == {"field": "username", "value": "StandardUser"}

    async def test_legacy_format_is_still_accepted(self, client: AsyncClient) -> None:
        """Регистрация пока принимает прежний набор символов — клиент валидирует по нему."""
        response = await self.register(client, "Ivan Petrov")

        assert response.status_code == 201
