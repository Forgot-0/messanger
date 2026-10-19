from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.profiles.dtos.profile_links import ProfileLinkDTO


class ProfileDTO(BaseModel):
    id: int
    username: str
    avatars: dict[int, dict[str, str]]
    specialization: str | None
    display_name: str | None
    bio: str | None
    date_birthday: date | None
    skills: set[str]
    links: list[ProfileLinkDTO]

    model_config = ConfigDict(from_attributes=True)

class AvatarPresign(BaseModel):
    url: str
    file_key: str


class ProfilePhotoDTO(BaseModel):
    id: UUID
    avatars: dict[int, dict[str, str]]
    is_main: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
