from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.chats.dtos.chats import PublicChatAvatarMixin
from app.chats.dtos.messages import MessageDTO
from app.chats.models.chat import ChatType


class SearchChatPreviewDTO(PublicChatAvatarMixin):
    id: UUID
    type: ChatType
    name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MessageSearchItemDTO(BaseModel):
    message: MessageDTO
    chat: SearchChatPreviewDTO


class MessageSearchDTO(BaseModel):
    has_next: bool
    items: list[MessageSearchItemDTO]
    next_message_id: UUID | None = None
