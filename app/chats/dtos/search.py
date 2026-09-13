from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.chats.dtos.messages import MessageDTO
from app.chats.models.chat import ChatType


class SearchChatPreviewDTO(BaseModel):
    """Минимум про чат, чтобы отрисовать строку результата без второго запроса."""

    id: UUID
    type: ChatType
    name: str | None = None

    avatar_url: str | None = None
    avatar_s3_key: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MessageSearchItemDTO(BaseModel):
    message: MessageDTO
    chat: SearchChatPreviewDTO


class MessageSearchDTO(BaseModel):
    """Курсорная страница — по образцу ListChats, has_next реальное поле."""

    has_next: bool
    items: list[MessageSearchItemDTO]
    next_message_id: UUID | None = None
