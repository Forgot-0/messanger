from pydantic import model_validator

from app.core.configs.app import app_config
from app.core.configs.base import BaseConfig


class ProfileConfig(BaseConfig):
    PENDING_AVATAR_BUCKET: str = "pending-avatar"
    AVATAR_BUCKET: str = "profiles"
    AVATAR_MAX_SIZE: int = 5*1024*1024
    AVATAR_MAX_PIXELS: int = 10_000_000
    AVATAR_ALLOWED_MIMES: frozenset[str] = frozenset(
        {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
    )


    MAX_LEN_SKILL_NAME: int = 30
    MAX_LEN_BIO: int = 1024
    MAX_LEN_DISPLAY_NAME: int = 100

    USER_TOPIC: str = "auth"
    USER_VERIFIED_GROUP_ID: str = "profiles-user-verified"
    USER_VERIFIED_EVENT: str = "auth.user.verified"

    CONTACT_IDENTIFIER_PEPPER: str = ""

    MAX_CONTACTS_PER_USER: int = 5_000
    MAX_LEN_CONTACT_NAME: int = 64
    MAX_LEN_EMAIL: int = 320
    MIN_PHONE_DIGITS: int = 8
    MAX_PHONE_DIGITS: int = 15

    CONTACT_OWNER_PERMISSIONS: frozenset[str] = frozenset({"profile:update", "user:update"})

    CONTACTS_IMPORT_MAX_BATCH: int = 500
    CONTACTS_IMPORT_RATE_TIMES: int = 5
    CONTACTS_IMPORT_RATE_SECONDS: int = 10 * 60

    CONTACTS_IMPORT_SYNC_THRESHOLD: int = 100
    CONTACTS_NEW_IDENTIFIERS_PER_DAY: int = 5_000
    IDENTIFIER_QUOTA_TTL: int = 24 * 60 * 60

    CONTACTS_PAGE_SIZE: int = 100
    CONTACTS_MAX_PAGE_SIZE: int = 500
    CONTACTS_SEARCH_LIMIT: int = 50
    CONTACTS_SEARCH_MIN_PREFIX: int = 2

    BLOCK_LIST_CACHE_TTL: int = 300

    PENDING_RESOLVE_BATCH_SIZE: int = 500
    PENDING_RESOLVE_MAX_EVENTS: int = 100

    @model_validator(mode="after")
    def validate_pepper(self) -> ProfileConfig:
        if app_config.ENVIRONMENT == "production" and not self.CONTACT_IDENTIFIER_PEPPER.strip():
            raise ValueError("Missing required production setting: CONTACT_IDENTIFIER_PEPPER")
        return self


profile_config = ProfileConfig()
