from typing import Any

import httpx
import pytest

from app.auth.exceptions import NoEmailOAuthError, UnverifiedEmailOAuthError
from app.auth.services.oauth_providers import OAuthGithub, OAuthGoogle, OAuthProvider, OAuthYandex

PROVIDER_ARGS = {
    "client_id": "client-id",
    "client_secret": "client-secret",
    "redirect_uri": "https://api.test/callback/",
    "base_auth_url": "https://provider.test/authorize",
    "token_url": "https://provider.test/token",
    "userinfo_url": "https://provider.test/userinfo",
}


def with_user_info(provider: OAuthProvider, payload: dict[str, Any]) -> OAuthProvider:
    async def _fetch_user_info(headers: dict[str, Any]) -> dict[str, Any]:
        return payload

    provider._fetch_user_info = _fetch_user_info  # type: ignore[method-assign]
    return provider


@pytest.fixture
def github_emails(monkeypatch: pytest.MonkeyPatch):
    class FakeResponse:
        def __init__(self, payload: Any) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> Any:
            return self._payload

    def _set(payload: Any) -> None:
        async def fake_get(self: Any, url: str, **kwargs: Any) -> FakeResponse:
            return FakeResponse(payload)

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    return _set


@pytest.mark.unit
@pytest.mark.auth
class TestGoogleUserInfo:

    @staticmethod
    def provider(payload: dict[str, Any]) -> OAuthGoogle:
        return with_user_info(OAuthGoogle(name="google", **PROVIDER_ARGS), payload)  # type: ignore[return-value]

    @pytest.mark.parametrize("email_verified", [True, "true", "True"])
    async def test_confirmed_email_is_accepted(self, email_verified: Any) -> None:
        provider = self.provider(
            {"sub": "1", "email": "user@example.com", "email_verified": email_verified, "name": "Иван Петров"}
        )

        data = await provider.get_user_info("token")

        assert data.email == "user@example.com"
        assert data.provider_user_id == "1"
        assert data.username == "Иван Петров"

    @pytest.mark.parametrize("email_verified", [False, "false", None, "", 0])
    async def test_unconfirmed_email_is_refused(self, email_verified: Any) -> None:
        provider = self.provider(
            {"sub": "1", "email": "victim@example.com", "email_verified": email_verified}
        )

        with pytest.raises(UnverifiedEmailOAuthError):
            await provider.get_user_info("token")

    async def test_missing_flag_is_refused(self) -> None:
        provider = self.provider({"sub": "1", "email": "victim@example.com"})

        with pytest.raises(UnverifiedEmailOAuthError):
            await provider.get_user_info("token")

    async def test_missing_email_is_refused(self) -> None:
        provider = self.provider({"sub": "1", "email_verified": True})

        with pytest.raises(NoEmailOAuthError):
            await provider.get_user_info("token")


@pytest.mark.unit
@pytest.mark.auth
class TestYandexUserInfo:

    @staticmethod
    def provider(payload: dict[str, Any]) -> OAuthYandex:
        return with_user_info(OAuthYandex(name="yandex", **PROVIDER_ARGS), payload)  # type: ignore[return-value]

    async def test_default_email_is_used(self) -> None:
        provider = self.provider(
            {"id": "42", "default_email": "user@yandex.ru", "emails": ["other@yandex.ru"], "login": "ivan"}
        )

        data = await provider.get_user_info("token")

        assert data.email == "user@yandex.ru"
        assert data.username == "ivan"

    async def test_falls_back_to_the_email_list(self) -> None:
        provider = self.provider({"id": "42", "emails": ["only@yandex.ru"], "login": "ivan"})

        assert (await provider.get_user_info("token")).email == "only@yandex.ru"

    async def test_display_name_is_used_when_there_is_no_login(self) -> None:
        provider = self.provider(
            {"id": "42", "default_email": "user@yandex.ru", "display_name": "Иван"}
        )

        assert (await provider.get_user_info("token")).username == "Иван"

    @pytest.mark.parametrize("payload", [{"id": "42"}, {"id": "42", "emails": []}])
    async def test_account_without_an_email_is_refused(self, payload: dict[str, Any]) -> None:
        provider = self.provider(payload)

        with pytest.raises(NoEmailOAuthError):
            await provider.get_user_info("token")


@pytest.mark.unit
@pytest.mark.auth
class TestGithubUserInfo:

    @staticmethod
    def provider() -> OAuthGithub:
        return with_user_info(  # type: ignore[return-value]
            OAuthGithub(name="github", **PROVIDER_ARGS),
            {"id": 7, "login": "Forgot-0"},
        )

    async def test_primary_confirmed_email_wins(self, github_emails) -> None:
        github_emails(
            [
                {"email": "second@example.com", "primary": False, "verified": True},
                {"email": "primary@example.com", "primary": True, "verified": True},
            ]
        )

        data = await self.provider().get_user_info("token")

        assert data.email == "primary@example.com"
        assert data.provider_user_id == "7"
        assert data.username == "Forgot-0"

    async def test_unconfirmed_primary_is_skipped(self, github_emails) -> None:
        github_emails(
            [
                {"email": "attacker-claimed@example.com", "primary": True, "verified": False},
                {"email": "real@example.com", "primary": False, "verified": True},
            ]
        )

        assert (await self.provider().get_user_info("token")).email == "real@example.com"

    async def test_no_confirmed_email_is_refused(self, github_emails) -> None:
        github_emails([{"email": "victim@example.com", "primary": True, "verified": False}])

        with pytest.raises(UnverifiedEmailOAuthError):
            await self.provider().get_user_info("token")

    async def test_empty_email_list_is_refused(self, github_emails) -> None:
        github_emails([])

        with pytest.raises(NoEmailOAuthError):
            await self.provider().get_user_info("token")
