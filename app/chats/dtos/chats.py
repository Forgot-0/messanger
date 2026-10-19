from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.chats.dtos.members import MemberChatDTO
from app.chats.dtos.messages import MessageDTO, ReadDetail
from app.chats.dtos.profiles import ChatProfileDTO
from app.chats.models.chat import ChatReactionsMode, ChatType
from app.core.utils import now_utc


class MutedByMeMixin(BaseModel):
    notifications_muted_until: datetime | None = None
    is_muted_by_me: bool = False

    @model_validator(mode="after")
    def _derive_is_muted_by_me(self) -> Self:
        self.is_muted_by_me = (
            self.notifications_muted_until is not None
            and self.notifications_muted_until > now_utc()
        )
        return self


class PublicChatAvatarMixin(BaseModel):
    avatar_s3_key: str | None = None
    avatar_url: str | None = None


class ChatAvatarMixin(PublicChatAvatarMixin):
    avatars: dict[str, dict[str, str]] = Field(default_factory=dict)


class ChatDTO(MutedByMeMixin, ChatAvatarMixin):
    id: UUID
    seq_counter: int
    last_activity_at: datetime | None

    type: ChatType
    name: str | None
    description: str | None
    username: str | None = None

    is_public: bool
    join_by_request: bool = False
    admin_only: bool = False
    slow_mode_seconds: int = 0
    permissions: dict[str, bool] = Field(default_factory=dict)
    reactions_mode: ChatReactionsMode = ChatReactionsMode.ALL
    allowed_reactions: list[str] = Field(default_factory=list)
    created_by: int

    member_count: int
    unread_count: int = 0

    me: MemberChatDTO | None = Field(default=None)
    last_read: ReadDetail | None = Field(default=None)
    last_message: MessageDTO | None = Field(default=None)

    peer: ChatProfileDTO | None = Field(default=None)
    members_preview: list[ChatProfileDTO] = Field(default_factory=list)

    is_pinned: bool = False
    pinned_at: datetime | None = None
    is_archived: bool = False
    draft: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ChatStateDTO(MutedByMeMixin):
    chat_id: UUID
    is_pinned: bool
    pinned_at: datetime | None
    is_archived: bool
    archived_at: datetime | None
    draft: str | None
    draft_updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ChatDetailDTO(ChatAvatarMixin):
    id: UUID
    seq_counter: int
    last_activity_at: datetime | None

    type: ChatType
    name: str | None
    description: str | None
    username: str | None = None

    is_public: bool
    join_by_request: bool = False
    admin_only: bool = False
    slow_mode_seconds: int = 0
    permissions: dict[str, bool] = Field(default_factory=dict)
    reactions_mode: ChatReactionsMode = ChatReactionsMode.ALL
    allowed_reactions: list[str] = Field(default_factory=list)
    created_by: int

    member_count: int
    members: list[MemberChatDTO]


class ListChats(BaseModel):
    has_next: bool
    chats: list[ChatDTO]
    next_date: datetime | None
    next_chat_id: UUID | None = None


class ChatPreviewDTO(ChatAvatarMixin):
    id: UUID
    type: ChatType
    name: str | None
    description: str | None
    username: str | None = None
    is_public: bool
    join_by_request: bool = False
    member_count: int
    is_member: bool = False

    model_config = ConfigDict(from_attributes=True)


class PublicChatSearchDTO(BaseModel):
    items: list[ChatPreviewDTO]
