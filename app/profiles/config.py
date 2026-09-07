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


profile_config = ProfileConfig()
