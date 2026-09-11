from dataclasses import dataclass

from app.core.exceptions import ApplicationError


@dataclass(kw_only=True)
class NotFoundProfileError(ApplicationError):
    profile_id: int

    code: str = "NOT_FOUND_PROFILE"
    status: int = 404

    @property
    def message(self) -> str:
        return "Profile not found"

    @property
    def detail(self) -> dict:
        return {"profile_id": self.profile_id}


@dataclass(kw_only=True)
class AlreadeExistProfileError(ApplicationError):
    code: str = "ALREADY_EXIST_PROFILE"
    status: int = 409

    @property
    def message(self) -> str:
        return "Profile already exist"

    @property
    def detail(self) -> dict:
        return {}


@dataclass(kw_only=True)
class TooLongSkillNameError(ApplicationError):
    name: str
    code: str = "TOO_LONG_SKILL_NAME"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Too long skill name {self.name}"

    @property
    def detail(self) -> dict:
        return {
            "skill_name": self.name
        }


@dataclass(kw_only=True)
class TooLongDisplayNameError(ApplicationError):
    name: str
    code: str = "TOO_LONG_DISPLAY_NAME"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Too long display name {self.name}"

    @property
    def detail(self) -> dict:
        return {
            "display_name": self.name
        }


@dataclass(kw_only=True)
class TooLongBioError(ApplicationError):
    bio: str
    code: str = "TOO_LONG_BIO"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Too long bio {self.bio}"

    @property
    def detail(self) -> dict:
        return {
            "bio": self.bio
        }


@dataclass(kw_only=True)
class AvatarNotImageTypeError(ApplicationError):
    type_avatar: str

    code: str = "AVATAR_NOT_TYPE_IMAGE"
    status: int = 400

    @property
    def message(self) -> str:
        return "Avatar must be image type(jpg, png, ...)"

    @property
    def detail(self) -> dict:
        return {
            "type": self.type_avatar
        }

@dataclass(kw_only=True)
class AvatarSizeError(ApplicationError):
    current_size: int

    code: str = "AVATAR_SIZE"
    status: int = 400

    @property
    def message(self) -> str:
        return "Avatar size"

    @property
    def detail(self) -> dict:
        return {
            "current_size": self.current_size
        }

@dataclass(kw_only=True)
class AvatarFileKeyError(ApplicationError):
    file_key: str

    code: str = "AVATAR_FILE_KEY"
    status: int = 400

    @property
    def message(self) -> str:
        return "Avatar file key is invalid"

    @property
    def detail(self) -> dict:
        return {"file_key": self.file_key}


@dataclass(kw_only=True)
class TooLongContactNameError(ApplicationError):
    name: str

    code: str = "TOO_LONG_CONTACT_NAME"
    status: int = 400

    @property
    def message(self) -> str:
        return "Too long contact name"

    @property
    def detail(self) -> dict:
        return {"name": self.name}


@dataclass(kw_only=True)
class NotFoundContactError(ApplicationError):
    contact_id: int

    code: str = "NOT_FOUND_CONTACT"
    status: int = 404

    @property
    def message(self) -> str:
        return "Contact not found"

    @property
    def detail(self) -> dict:
        return {"contact_id": self.contact_id}


@dataclass(kw_only=True)
class NotFoundContactTargetError(ApplicationError):
    user_id: int | None = None
    username: str | None = None

    code: str = "NOT_FOUND_CONTACT_TARGET"
    status: int = 404

    @property
    def message(self) -> str:
        return "User to add is not found"

    @property
    def detail(self) -> dict:
        return {"user_id": self.user_id, "username": self.username}


@dataclass(kw_only=True)
class SelfContactError(ApplicationError):
    code: str = "SELF_CONTACT_NOT_ALLOWED"
    status: int = 400

    @property
    def message(self) -> str:
        return "Cannot add or block yourself"

    @property
    def detail(self) -> dict:
        return {}


@dataclass(kw_only=True)
class ContactLimitExceededError(ApplicationError):
    limit: int

    code: str = "CONTACT_LIMIT_EXCEEDED"
    status: int = 409

    @property
    def message(self) -> str:
        return "Contact limit exceeded"

    @property
    def detail(self) -> dict:
        return {"limit": self.limit}


@dataclass(kw_only=True)
class ContactBlockedError(ApplicationError):
    user_id: int

    code: str = "CONTACT_BLOCKED"
    status: int = 409

    @property
    def message(self) -> str:
        return "User is blocked, unblock first"

    @property
    def detail(self) -> dict:
        return {"user_id": self.user_id}


@dataclass(kw_only=True)
class ImportBatchTooLargeError(ApplicationError):
    limit: int
    current: int

    code: str = "IMPORT_BATCH_TOO_LARGE"
    status: int = 400

    @property
    def message(self) -> str:
        return "Import batch is too large"

    @property
    def detail(self) -> dict:
        return {"limit": self.limit, "current": self.current}


@dataclass(kw_only=True)
class IdentifierQuotaExceededError(ApplicationError):
    limit: int

    code: str = "IDENTIFIER_QUOTA_EXCEEDED"
    status: int = 429

    @property
    def message(self) -> str:
        return "Daily identifier quota exceeded"

    @property
    def detail(self) -> dict:
        return {"limit": self.limit, "period": "24h"}


@dataclass(kw_only=True)
class IdentifierPepperNotConfiguredError(ApplicationError):
    code: str = "IDENTIFIER_PEPPER_NOT_CONFIGURED"
    status: int = 503

    @property
    def message(self) -> str:
        return "Contact identifier hashing is not configured"

    @property
    def detail(self) -> dict:
        return {}
