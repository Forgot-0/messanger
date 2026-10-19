from app.core.configs.base import BaseConfig


class AuthConfig(BaseConfig):
    EMAIL_RESET_TOKEN_EXPIRE_MINUTES: int = 15
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 5
    REFRESH_TOKEN_EXPIRE_DAYS: int = 60

    # OAuth Google
    OAUTH_GOOGLE_CLIENT_ID: str = ""
    OAUTH_GOOGLE_CLIENT_SECRET: str = ""
    OAUTH_GOOGLE_REDIRECT_URI: str = ""
    OAUTH_GOOGLE_BASE_AUTH_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"
    OAUTH_GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token" # noqa: S105
    OAUTH_GOOGLE_USERINFO_URL: str = "https://openidconnect.googleapis.com/v1/userinfo"

    # OAuth Yandex
    OAUTH_YANDEX_CLIENT_ID: str = ""
    OAUTH_YANDEX_CLIENT_SECRET: str = ""
    OAUTH_YANDEX_REDIRECT_URI: str = ""
    OAUTH_YANDEX_BASE_AUTH_URL: str = "https://oauth.yandex.ru/authorize"
    OAUTH_YANDEX_TOKEN_URL: str = "https://oauth.yandex.ru/token" # noqa: S105
    OAUTH_YANDEX_USERINFO_URL: str = "https://login.yandex.ru/info"

    # OAuth GitHub
    OAUTH_GITHUB_CLIENT_ID: str = ""
    OAUTH_GITHUB_CLIENT_SECRET: str = ""
    OAUTH_GITHUB_REDIRECT_URI: str = ""
    OAUTH_GITHUB_BASE_AUTH_URL: str = "https://github.com/login/oauth/authorize"
    OAUTH_GITHUB_TOKEN_URL: str = "https://github.com/login/oauth/access_token" # noqa: S105
    OAUTH_GITHUB_USERINFO_URL: str = "https://api.github.com/user"

    USER_TOPIC: str = "auth"
    SEND_VERIFY_GROUP_ID: str = "send-verify-email"

    USERNAME_MIN_LENGTH: int = 5
    USERNAME_MAX_LENGTH: int = 32
    USERNAME_RESERVED: frozenset[str] = frozenset({
        "admin", "administrator", "moderator", "support", "help", "helpdesk",
        "system", "official", "security", "abuse", "root", "superuser", "staff",
        "service", "notifications", "bot", "username", "settings", "privacy",
        "profile", "profiles", "contacts", "account", "chatix", "telegram",
        "deleted", "anonymous", "null", "undefined",
    })
    USERNAME_CHANGE_RATE_TIMES: int = 5
    USERNAME_CHANGE_RATE_SECONDS: int = 60 * 60
    USERNAME_CHECK_RATE_TIMES: int = 30
    USERNAME_CHECK_RATE_SECONDS: int = 60


auth_config = AuthConfig()
