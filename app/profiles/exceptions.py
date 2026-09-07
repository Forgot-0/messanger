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
