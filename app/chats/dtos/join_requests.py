from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.chats.dtos.chats import ChatDTO
from app.chats.dtos.profiles import ChatProfileDTO
from app.chats.models.join_request import JoinRequestStatus


class ChatJoinRequestDTO(BaseModel):
    chat_id: UUID
    user_id: int
    status: JoinRequestStatus
    invite_link_id: UUID | None = None
    requested_at: datetime
    resolved_at: datetime | None = None
    resolved_by: int | None = None

    profile: ChatProfileDTO | None = None

    model_config = ConfigDict(from_attributes=True)


class ListJoinRequests(BaseModel):
    requests: list[ChatJoinRequestDTO] = Field(default_factory=list)
    total: int
    has_next: bool
    next_requested_at: datetime | None = None
    next_user_id: int | None = None


class JoinRequestsResolutionDTO(BaseModel):
    resolved: list[int] = Field(default_factory=list)
    skipped: list[int] = Field(default_factory=list)


class JoinRequestsDismissedDTO(BaseModel):
    declined: int


class JoinResultStatus(StrEnum):
    JOINED = "joined"
    REQUESTED = "requested"


class JoinChatResultDTO(BaseModel):
    status: JoinResultStatus
    chat: ChatDTO | None = None
    join_request: ChatJoinRequestDTO | None = None
