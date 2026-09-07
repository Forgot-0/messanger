from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.chats.dtos.members import MemberChatDTO
from app.chats.dtos.messages import MessageDTO, ReadDetail
from app.chats.models.chat import ChatReactionsMode, ChatType


class ChatDTO(BaseModel):
    id: UUID
    seq_counter: int
    last_activity_at: datetime | None

    type: ChatType
    name: str | None
    description: str | None
    avatar_s3_key: str | None

    is_public: bool
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

    model_config = ConfigDict(from_attributes=True)


class ChatDetailDTO(BaseModel):
    id: UUID
    seq_counter: int
    last_activity_at: datetime | None

    type: ChatType
    name: str | None
    description: str | None
    avatar_s3_key: str | None

    is_public: bool
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
