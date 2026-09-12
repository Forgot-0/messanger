from dishka import Provider, Scope, alias, decorate, provide, provide_all
from passlib.context import CryptContext
from redis.asyncio import Redis

from app.auth.commands.auth.auth_url import CreateOAuthAuthorizeUrlCommand, CreateOAuthAuthorizeUrlCommandHandler
from app.auth.commands.auth.login import LoginCommand, LoginCommandHandler
from app.auth.commands.auth.logout import LogoutCommand, LogoutCommandHandler
from app.auth.commands.auth.oauth import (
    ProcessOAuthCallbackCommand,
    ProcessOAuthCallbackCommandHandler,
)
from app.auth.commands.auth.refresh_token import RefreshTokenCommand, RefreshTokenCommandHandler
from app.auth.commands.permissions.add_permission_user import (
    AddPermissionToUserCommand,
    AddPermissionToUserCommandHandler,
)
from app.auth.commands.permissions.create import CreatePermissionCommand, CreatePermissionCommandHandler
from app.auth.commands.permissions.delete import DeletePermissionCommand, DeletePermissionCommandHandler
from app.auth.commands.permissions.remove_permission_user import (
    DeletePermissionToUserCommand,
    DeletePermissionToUserCommandHandler,
)
from app.auth.commands.roles.add_permissions import AddPermissionRoleCommand, AddPermissionRoleCommandHandler
from app.auth.commands.roles.assign_role_to_user import AssignRoleCommand, AssignRoleCommandHandler
from app.auth.commands.roles.create import CreateRoleCommand, CreateRoleCommandHandler
from app.auth.commands.roles.delete_permissions import DeletePermissionRoleCommand, DeletePermissionRoleCommandHandler
from app.auth.commands.roles.remove_role_user import RemoveRoleCommand, RemoveRoleCommandHandler
from app.auth.commands.roles.update import RoleUpdateCommand, RoleUpdateCommandHandler
from app.auth.commands.sessions.deactivate_session import (
    UserDeactivateSessionCommand,
    UserDeactivateSessionCommandHandler,
)
from app.auth.commands.users.register import RegisterCommand, RegisterCommandHandler
from app.auth.commands.users.reset_password import ResetPasswordCommand, ResetPasswordCommandHandler
from app.auth.commands.users.send_reset_password import SendResetPasswordCommand, SendResetPasswordCommandHandler
from app.auth.commands.users.send_verify import SendVerifyCommand, SendVerifyCommandHandler
from app.auth.commands.users.verify import VerifyCommand, VerifyCommandHandler
from app.auth.config import auth_config
from app.auth.queries.auth.get_by_token import GetByAccessTokenQuery, GetByAccessTokenQueryHandler
from app.auth.queries.auth.oauth import GetUserOAuthAccountsQuery, GetUserOAuthAccountsQueryHandler
from app.auth.queries.auth.verify import VerifyTokenQuery, VerifyTokenQueryHandler
from app.auth.queries.permissions.get_list import GetListPermissionsQuery, GetListPermissionsQueryHandler
from app.auth.queries.roles.get_list import GetListRolesQuery, GetListRolesQueryHandler
from app.auth.queries.sessions.get_list import GetListSessionQuery, GetListSessionQueryHandler
from app.auth.queries.sessions.get_list_by_user import GetListSessionsUserQuery, GetListSessionsUserQueryHandler
from app.auth.queries.users.get_list import GetListUserQuery, GetListUserQueryHandler
from app.auth.repositories.oauth import OauthAccountRepository, OAuthCodeRepository
from app.auth.repositories.permission import PermissionInvalidateRepository, PermissionRepository
from app.auth.repositories.role import RoleInvalidateRepository, RoleRepository
from app.auth.repositories.session import SessionRepository, TokenBlacklistRepository
from app.auth.repositories.user import UserRepository
from app.auth.services.cookie_manager import IRefreshTokenCookieManager, RefreshTokenCookieManager
from app.auth.services.hash import HashService
from app.auth.services.jwt import AuthJWTManager
from app.auth.services.oauth_manager import OAuthManager, OAuthProviderFactory
from app.auth.services.oauth_providers import OAuthGithub, OAuthGoogle, OAuthYandex
from app.auth.services.rbac import AuthRBACManager
from app.auth.services.session import SessionManager
from app.core.configs.app import app_config
from app.core.mediators.base import CommandRegistry, QueryRegistry
from app.core.services.auth.rbac import RBACManagerInterface


class AuthModuleProvider(Provider):
    scope = Scope.REQUEST

    repositories = provide_all(
        UserRepository,
        SessionRepository,
        RoleRepository,
        PermissionRepository,
        OauthAccountRepository,
    )

    @provide(scope=Scope.APP)
    def token_blacklist(self, redis: Redis) -> TokenBlacklistRepository:
        return TokenBlacklistRepository(
            client=redis
        )

    @provide(scope=Scope.APP)
    def role_blacklist(self, redis: Redis) -> RoleInvalidateRepository:
        return RoleInvalidateRepository(
            client=redis
        )

    @provide(scope=Scope.APP)
    def permission_blacklist(self, redis: Redis) -> PermissionInvalidateRepository:
        return PermissionInvalidateRepository(
            client=redis
        )

    @provide(scope=Scope.APP)
    def oauth_code_repository(self, redis: Redis) -> OAuthCodeRepository:
        return OAuthCodeRepository(
            client=redis
        )

    #services
    @provide(scope=Scope.APP)
    def cookie_manager(self) -> RefreshTokenCookieManager:
        if app_config.ENVIRONMENT != "production":
            return IRefreshTokenCookieManager(
                SAMESITE="none",
                HTTPONLY=False,
                SECURE=False
            )

        return IRefreshTokenCookieManager(
            SAMESITE="strict",
            HTTPONLY=True,
            SECURE=True
        )

    @provide(scope=Scope.APP)
    def hash_service(self) -> HashService:
        return HashService(
            CryptContext(schemes=["argon2"], deprecated="auto")
        )

    jwt_manager = provide(AuthJWTManager, scope=Scope.APP)

    @provide(scope=Scope.APP)
    def oauth_factory(self) -> OAuthProviderFactory:
        provider_factory =  OAuthProviderFactory()

        if auth_config.OAUTH_GOOGLE_CLIENT_ID:
            provider_factory.register_provider(
                OAuthGoogle(
                    name="google",
                    client_id=auth_config.OAUTH_GOOGLE_CLIENT_ID,
                    client_secret=auth_config.OAUTH_GOOGLE_CLIENT_SECRET,
                    redirect_uri=auth_config.OAUTH_GOOGLE_REDIRECT_URI,
                    base_auth_url=auth_config.OAUTH_GOOGLE_BASE_AUTH_URL,
                    token_url=auth_config.OAUTH_GOOGLE_TOKEN_URL,
                    userinfo_url=auth_config.OAUTH_GOOGLE_USERINFO_URL
                )
            )

        if auth_config.OAUTH_YANDEX_CLIENT_ID:
            provider_factory.register_provider(
                OAuthYandex(
                    name="yandex",
                    client_id=auth_config.OAUTH_YANDEX_CLIENT_ID,
                    client_secret=auth_config.OAUTH_YANDEX_CLIENT_SECRET,
                    redirect_uri=auth_config.OAUTH_YANDEX_REDIRECT_URI,
                    base_auth_url=auth_config.OAUTH_YANDEX_BASE_AUTH_URL,
                    token_url=auth_config.OAUTH_YANDEX_TOKEN_URL,
                    userinfo_url=auth_config.OAUTH_YANDEX_USERINFO_URL
                )
            )

        if auth_config.OAUTH_GITHUB_CLIENT_ID:
            provider_factory.register_provider(
                OAuthGithub(
                    name="github",
                    client_id=auth_config.OAUTH_GITHUB_CLIENT_ID,
                    client_secret=auth_config.OAUTH_GITHUB_CLIENT_SECRET,
                    redirect_uri=auth_config.OAUTH_GITHUB_REDIRECT_URI,
                    base_auth_url=auth_config.OAUTH_GITHUB_BASE_AUTH_URL,
                    token_url=auth_config.OAUTH_GITHUB_TOKEN_URL,
                    userinfo_url=auth_config.OAUTH_GITHUB_USERINFO_URL
                )
            )

        return provider_factory


    @provide(scope=Scope.APP)
    def rbac_manager(self) -> AuthRBACManager:
        return AuthRBACManager()

    rbac_manager_port = alias(source=AuthRBACManager, provides=RBACManagerInterface)

    handlers = provide_all(
        SessionManager,
        OAuthManager,

        RegisterCommandHandler,
        ResetPasswordCommandHandler,
        SendResetPasswordCommandHandler,
        SendVerifyCommandHandler,
        VerifyCommandHandler,
        LoginCommandHandler,
        LogoutCommandHandler,
        RefreshTokenCommandHandler,
        CreateOAuthAuthorizeUrlCommandHandler,
        ProcessOAuthCallbackCommandHandler,
        CreateRoleCommandHandler,
        RoleUpdateCommandHandler,
        AssignRoleCommandHandler,
        RemoveRoleCommandHandler,
        AddPermissionRoleCommandHandler,
        DeletePermissionRoleCommandHandler,
        CreatePermissionCommandHandler,
        DeletePermissionCommandHandler,
        AddPermissionToUserCommandHandler,
        DeletePermissionToUserCommandHandler,
        UserDeactivateSessionCommandHandler,

        VerifyTokenQueryHandler,
        GetListUserQueryHandler,
        GetByAccessTokenQueryHandler,
        GetListPermissionsQueryHandler,
        GetListRolesQueryHandler,
        GetListSessionsUserQueryHandler,
        GetListSessionQueryHandler,
        GetUserOAuthAccountsQueryHandler

    )

    @decorate
    def register_auth_command_handlers(self, command_registry: CommandRegistry) -> CommandRegistry:
        command_registry.register_command(RegisterCommand, RegisterCommandHandler)
        command_registry.register_command(VerifyCommand, VerifyCommandHandler)
        command_registry.register_command(SendVerifyCommand, SendVerifyCommandHandler)
        command_registry.register_command(ResetPasswordCommand, ResetPasswordCommandHandler)
        command_registry.register_command(SendResetPasswordCommand, SendResetPasswordCommandHandler)

        command_registry.register_command(LoginCommand, LoginCommandHandler)
        command_registry.register_command(LogoutCommand, LogoutCommandHandler)
        command_registry.register_command(RefreshTokenCommand, RefreshTokenCommandHandler)

        command_registry.register_command(CreateOAuthAuthorizeUrlCommand, CreateOAuthAuthorizeUrlCommandHandler)
        command_registry.register_command(ProcessOAuthCallbackCommand, ProcessOAuthCallbackCommandHandler)

        command_registry.register_command(CreateRoleCommand, CreateRoleCommandHandler)
        command_registry.register_command(AssignRoleCommand, AssignRoleCommandHandler)
        command_registry.register_command(RemoveRoleCommand, RemoveRoleCommandHandler)
        command_registry.register_command(AddPermissionRoleCommand, AddPermissionRoleCommandHandler)
        command_registry.register_command(DeletePermissionRoleCommand, DeletePermissionRoleCommandHandler)
        command_registry.register_command(RoleUpdateCommand, RoleUpdateCommandHandler)

        command_registry.register_command(CreatePermissionCommand, CreatePermissionCommandHandler)
        command_registry.register_command(DeletePermissionCommand, DeletePermissionCommandHandler)
        command_registry.register_command(AddPermissionToUserCommand, AddPermissionToUserCommandHandler)
        command_registry.register_command(DeletePermissionToUserCommand, DeletePermissionToUserCommandHandler)

        command_registry.register_command(UserDeactivateSessionCommand, UserDeactivateSessionCommandHandler)
        return command_registry

    @decorate
    def register_auth_query_handlers(self, query_registry: QueryRegistry) -> QueryRegistry:
        query_registry.register_query(GetByAccessTokenQuery, GetByAccessTokenQueryHandler)
        query_registry.register_query(VerifyTokenQuery, VerifyTokenQueryHandler)

        query_registry.register_query(GetUserOAuthAccountsQuery, GetUserOAuthAccountsQueryHandler)

        query_registry.register_query(GetListUserQuery, GetListUserQueryHandler)

        query_registry.register_query(GetListPermissionsQuery, GetListPermissionsQueryHandler)

        query_registry.register_query(GetListRolesQuery, GetListRolesQueryHandler)

        query_registry.register_query(GetListSessionsUserQuery, GetListSessionsUserQueryHandler)
        query_registry.register_query(GetListSessionQuery, GetListSessionQueryHandler)
        return query_registry
