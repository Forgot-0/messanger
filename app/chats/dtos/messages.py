from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.chats.dtos.attachments import AttachmentDTO
from app.chats.dtos.profiles import ChatProfileDTO
from app.chats.dtos.reactions import ReactionGroupDTO
from app.chats.models.message import MessageType


class MessageDTO(BaseModel):
    id: UUID
    chat_id: UUID
    seq: int
    author_id: int | None
    type: MessageType
    content: str | None
    reply_to_id: UUID | None
    forwarded_from_chat_id: UUID | None
    forwarded_from_message_id: UUID | None
    forwarded_from_author_id: int | None

    is_edited: bool
    created_at: datetime

    profile: ChatProfileDTO | None = Field(default=None)
    attachments: list[AttachmentDTO] = Field(default_factory=list)
    reactions: list[ReactionGroupDTO] = Field(default_factory=list)

    reply_to: MessageDTO | None = Field(default=None)
    forwarded_from: MessageDTO | None = Field(default=None)

    model_config = ConfigDict(from_attributes=True)


class ReadDetail(BaseModel):
    last_read_message_seq: int
    last_read_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessagesDTO(BaseModel):
    messages: list[MessageDTO]
    next_cursor: int | None
    has_next: bool

    model_config = ConfigDict(from_attributes=True)
