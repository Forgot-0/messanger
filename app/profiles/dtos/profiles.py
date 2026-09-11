from datetime import date

from pydantic import BaseModel, ConfigDict

from app.profiles.dtos.profile_links import ProfileLinkDTO


class ProfileDTO(BaseModel):
    id: int
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
