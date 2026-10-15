from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.chats.dtos.chats import ChatPreviewDTO


class ChatInviteLinkDTO(BaseModel):
    id: UUID
    chat_id: UUID
    code: str
    name: str | None
    created_by: int
    created_at: datetime
    expires_at: datetime | None
    usage_limit: int | None
    usage_count: int
    revoked_at: datetime | None
    is_revoked: bool
    is_expired: bool
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class ListInviteLinks(BaseModel):
    invites: list[ChatInviteLinkDTO]
    has_next: bool
    next_invite_id: UUID | None = None


class ChatInvitePreviewDTO(BaseModel):
    chat: ChatPreviewDTO
    expires_at: datetime | None
