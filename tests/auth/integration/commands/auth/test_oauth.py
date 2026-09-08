import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.commands.auth.auth_url import (
    CreateOAuthAuthorizeUrlCommand,
    CreateOAuthAuthorizeUrlCommandHandler,
)
from app.auth.commands.auth.oauth import (
    ProcessOAuthCallbackCommand,
    ProcessOAuthCallbackCommandHandler,
)
from app.auth.dtos.tokens import OAuthData
from app.auth.exceptions import (
    LinkedAnotherUserOAuthError,
    NotExistProviderOAuthError,
    OAuthStateNotFoundError,
)
from app.auth.models.oauth import OAuthAccount, OAuthProviderEnum
from app.auth.models.user import User
from app.auth.repositories.oauth import OauthAccountRepository, OAuthCodeRepository
from app.auth.repositories.user import UserRepository
from app.auth.services.jwt import AuthJWTManager
from app.auth.services.oauth_manager import OAuthProviderFactory
from tests.mocks import FakeOAuthProvider

PROVIDER = "google"


@pytest.fixture
async def fake_provider(di_container: AsyncContainer) -> FakeOAuthProvider:
    factory = await di_container.get(OAuthProviderFactory)
    provider = factory.get_provider(PROVIDER)
    assert isinstance(provider, FakeOAuthProvider)
    return provider


@pytest.fixture
async def oauth_account_repository(
    request_container: AsyncContainer,
) -> OauthAccountRepository:
    return await request_container.get(OauthAccountRepository)


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestCreateOAuthAuthorizeUrl:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> CreateOAuthAuthorizeUrlCommandHandler:
        return await request_container.get(CreateOAuthAuthorizeUrlCommandHandler)

    async def test_url_points_at_the_provider_and_carries_a_state(
        self,
        handler: CreateOAuthAuthorizeUrlCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
    ) -> None:
        url = await handler.handle(
            CreateOAuthAuthorizeUrlCommand(provider=PROVIDER, user_id=None)
        )

        assert url.startswith("https://accounts.test/authorize?")
        state = url.split("state=")[1]
        assert await oauth_code_repository.get_state(state) is not None

    async def test_state_is_unique_per_call(
        self,
        handler: CreateOAuthAuthorizeUrlCommandHandler,
    ) -> None:
        command = CreateOAuthAuthorizeUrlCommand(provider=PROVIDER, user_id=None)

        first = await handler.handle(command)
        second = await handler.handle(command)

        assert first.split("state=")[1] != second.split("state=")[1]

    async def test_login_flow_stores_zero_as_the_owner(
        self,
        handler: CreateOAuthAuthorizeUrlCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
    ) -> None:
        url = await handler.handle(
            CreateOAuthAuthorizeUrlCommand(provider=PROVIDER, user_id=None)
        )

        assert await oauth_code_repository.get_state(url.split("state=")[1]) == 0

    async def test_connect_flow_stores_the_user_id(
        self,
        handler: CreateOAuthAuthorizeUrlCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        standard_user: User,
    ) -> None:
        url = await handler.handle(
            CreateOAuthAuthorizeUrlCommand(provider=PROVIDER, user_id=standard_user.id)
        )

        assert await oauth_code_repository.get_state(
            url.split("state=")[1]
        ) == standard_user.id

    async def test_unknown_provider_is_rejected(
        self,
        handler: CreateOAuthAuthorizeUrlCommandHandler,
    ) -> None:
        with pytest.raises(NotExistProviderOAuthError):
            await handler.handle(
                CreateOAuthAuthorizeUrlCommand(provider="myspace", user_id=None)
            )


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestProcessOAuthCallback:

    @pytest.fixture
    async def handler(
        self, request_container: AsyncContainer
    ) -> ProcessOAuthCallbackCommandHandler:
        return await request_container.get(ProcessOAuthCallbackCommandHandler)

    @staticmethod
    def callback(state: str, code: str = "auth-code") -> ProcessOAuthCallbackCommand:
        return ProcessOAuthCallbackCommand(
            provider=PROVIDER,
            code=code,
            state=state,
            user_agent="Chrome/100.0",
            ip_address="127.0.0.1",
        )

    async def _state_for(
        self, repository: OAuthCodeRepository, user_id: int | None
    ) -> str:
        state = "state-token"
        await repository.add_oauth_state(state, user_id)
        return state

    async def test_new_user_is_created_with_the_standard_role(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        user_repository: UserRepository,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        fake_provider.user_info = OAuthData(
            provider_user_id="ext-new", email="brand.new@example.com", username="new"
        )
        state = await self._state_for(oauth_code_repository, None)

        tokens = await handler.handle(self.callback(state))

        assert tokens.access_token and tokens.refresh_token

        created = await user_repository.get_by_email("brand.new@example.com")
        assert created is not None
        assert created.is_verified is True
        assert created.password_hash is None

        with_roles = await user_repository.get_user_with_permission_by_id(created.id)
        assert with_roles is not None
        assert {r.name for r in with_roles.roles} == {"user"}

    async def test_new_user_gets_a_linked_oauth_account(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        oauth_account_repository: OauthAccountRepository,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        fake_provider.user_info = OAuthData(
            provider_user_id="ext-linked", email="linked@example.com", username="l"
        )
        state = await self._state_for(oauth_code_repository, None)

        await handler.handle(self.callback(state))

        account = await oauth_account_repository.get_by_provider_and_user_id(
            provider=OAuthProviderEnum(PROVIDER), provider_user_id="ext-linked"
        )
        assert account is not None
        assert account.provider_email == "linked@example.com"

    async def test_token_carries_the_new_user_id(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        user_repository: UserRepository,
        auth_jwt_manager: AuthJWTManager,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        fake_provider.user_info = OAuthData(
            provider_user_id="ext-sub", email="sub@example.com", username="s"
        )
        state = await self._state_for(oauth_code_repository, None)

        tokens = await handler.handle(self.callback(state))

        created = await user_repository.get_by_email("sub@example.com")
        assert created is not None
        token_data = await auth_jwt_manager.validate_token(tokens.access_token)
        assert token_data.sub == str(created.id)

    async def test_existing_oauth_account_logs_the_same_user_in(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        db_session: AsyncSession,
        standard_user: User,
        auth_jwt_manager: AuthJWTManager,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        db_session.add(
            OAuthAccount(
                provider=OAuthProviderEnum(PROVIDER),
                provider_email=standard_user.email,
                provider_user_id="ext-known",
                user_id=standard_user.id,
            )
        )
        await db_session.commit()

        fake_provider.user_info = OAuthData(
            provider_user_id="ext-known", email=standard_user.email, username="x"
        )
        state = await self._state_for(oauth_code_repository, None)

        tokens = await handler.handle(self.callback(state))

        token_data = await auth_jwt_manager.validate_token(tokens.access_token)
        assert token_data.sub == str(standard_user.id)

    async def test_email_taken_by_a_password_account_is_refused(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        standard_user: User,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        fake_provider.user_info = OAuthData(
            provider_user_id="ext-takeover", email=standard_user.email, username="t"
        )
        state = await self._state_for(oauth_code_repository, None)

        with pytest.raises(LinkedAnotherUserOAuthError):
            await handler.handle(self.callback(state))

    async def test_connect_links_the_account_to_the_current_user(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        oauth_account_repository: OauthAccountRepository,
        standard_user: User,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        fake_provider.user_info = OAuthData(
            provider_user_id="ext-connect", email="connect@example.com", username="c"
        )
        state = await self._state_for(oauth_code_repository, standard_user.id)

        await handler.handle(self.callback(state))

        account = await oauth_account_repository.get_by_provider_and_user_id(
            provider=OAuthProviderEnum(PROVIDER), provider_user_id="ext-connect"
        )
        assert account is not None
        assert account.user_id == standard_user.id

    async def test_account_already_linked_to_someone_else_is_refused(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        db_session: AsyncSession,
        standard_user: User,
        admin_user: User,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        db_session.add(
            OAuthAccount(
                provider=OAuthProviderEnum(PROVIDER),
                provider_email="taken@example.com",
                provider_user_id="ext-taken",
                user_id=admin_user.id,
            )
        )
        await db_session.commit()

        fake_provider.user_info = OAuthData(
            provider_user_id="ext-taken", email="taken@example.com", username="t"
        )
        state = await self._state_for(oauth_code_repository, standard_user.id)

        with pytest.raises(LinkedAnotherUserOAuthError):
            await handler.handle(self.callback(state))

    async def test_unknown_state_is_refused(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
    ) -> None:
        with pytest.raises(OAuthStateNotFoundError):
            await handler.handle(self.callback("never-issued"))

    async def test_state_is_consumed_after_a_successful_callback(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        fake_provider.user_info = OAuthData(
            provider_user_id="ext-once", email="once@example.com", username="o"
        )
        state = await self._state_for(oauth_code_repository, None)

        await handler.handle(self.callback(state))

        assert await oauth_code_repository.get_state(state) is None

    async def test_replaying_the_same_state_is_refused(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        fake_provider.user_info = OAuthData(
            provider_user_id="ext-replay", email="replay@example.com", username="r"
        )
        state = await self._state_for(oauth_code_repository, None)
        await handler.handle(self.callback(state))

        with pytest.raises(OAuthStateNotFoundError):
            await handler.handle(self.callback(state))

    async def test_authorization_code_is_exchanged_once(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        fake_provider.user_info = OAuthData(
            provider_user_id="ext-code", email="code@example.com", username="c"
        )
        fake_provider.exchanged_codes.clear()
        state = await self._state_for(oauth_code_repository, None)

        await handler.handle(self.callback(state, code="the-code"))

        assert fake_provider.exchanged_codes == ["the-code"]

    async def test_provider_failure_propagates(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
        fake_provider: FakeOAuthProvider,
    ) -> None:
        fake_provider.exchange_error = RuntimeError("провайдер недоступен")
        state = await self._state_for(oauth_code_repository, None)

        with pytest.raises(RuntimeError):
            await handler.handle(self.callback(state))

    async def test_unknown_provider_in_the_callback_is_rejected(
        self,
        handler: ProcessOAuthCallbackCommandHandler,
        oauth_code_repository: OAuthCodeRepository,
    ) -> None:
        state = await self._state_for(oauth_code_repository, None)

        with pytest.raises(NotExistProviderOAuthError):
            await handler.handle(
                ProcessOAuthCallbackCommand(
                    provider="myspace",
                    code="c",
                    state=state,
                    user_agent="Chrome/100.0",
                    ip_address="127.0.0.1",
                )
            )
