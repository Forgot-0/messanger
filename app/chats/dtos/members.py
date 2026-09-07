from pydantic import BaseModel, ConfigDict, Field

from app.chats.dtos.profiles import ChatProfileDTO


class Role(BaseModel):
    id: int
    name: str
    level: int
    permissions: dict[str, bool] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class MemberChatDTO(BaseModel):
    user_id: int
    role_id: int
    is_muted: bool
    is_banned: bool
    permissions_overrides: dict[str, bool] = Field(default_factory=dict)

    profile: ChatProfileDTO | None = None

    model_config = ConfigDict(from_attributes=True)


class MemberPresenceDTO(BaseModel):
    user_id: int
    is_online: bool


class ListMembers(BaseModel):
    members: list[MemberChatDTO]
    has_next: bool
    next_user_id: int | None = None
    presence: list[MemberPresenceDTO] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
