from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.chats.dtos.messages import MessageDTO


class PinnedMessageDTO(BaseModel):
    message: MessageDTO
    pinned_by: int
    pinned_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PinnedMessagesDTO(BaseModel):
    items: list[PinnedMessageDTO]
    total: int
    has_next: bool
    next_cursor: int | None = None
