from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.chats.models.attachment import AttachmentStatus, AttachmentType, HlsStatus


class AttachmentPreviewDTO(BaseModel):
    size: int
    width: int
    height: int
    mime_type: str
    file_size: int
    s3_key: str
    url: str | None = None
    url_expires_in: int | None = None


class AttachmentDTO(BaseModel):
    id: UUID
    message_id: UUID | None
    chat_id: UUID
    uploader_id: int
    attachment_type: AttachmentType
    attachment_status: AttachmentStatus
    url: str | None = None
    url_expires_in: int | None = None
    s3_key: str
    mime_type: str
    original_filename: str
    size: int

    width: int | None
    height: int | None
    duration_seconds: int | None

    thumbhash: str | None = None
    previews: list[AttachmentPreviewDTO] = Field(default_factory=list)
    hls_status: HlsStatus | None = None
    hls_url: str | None = None
    hls_key: str | None = Field(default=None, exclude=True)

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("previews", mode="before")
    @classmethod
    def _previews_or_empty(cls, value: Any) -> Any:
        return [] if value is None else value


class AttachmentDownloadUrlDTO(BaseModel):
    attachment_id: UUID
    url: str
    expires_in: int
    hls_url: str | None = None


class SharedMediaType(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    MEDIA = "media"
    FILE = "file"
    VOICE = "voice"
    LINK = "link"


SHARED_MEDIA_ATTACHMENT_TYPES: dict[SharedMediaType, tuple[AttachmentType, ...]] = {
    SharedMediaType.PHOTO: (AttachmentType.IMAGE,),
    SharedMediaType.VIDEO: (AttachmentType.VIDEO,),
    SharedMediaType.MEDIA: (AttachmentType.IMAGE, AttachmentType.VIDEO),
    SharedMediaType.FILE: (AttachmentType.FILE,),
    SharedMediaType.VOICE: (AttachmentType.VOICE, AttachmentType.VIDEO_NOTE),
}


class SharedMediaItemDTO(BaseModel):
    message_id: UUID
    message_seq: int
    author_id: int | None
    content: str | None
    created_at: datetime
    attachment: AttachmentDTO | None = None


class SharedMediaDTO(BaseModel):
    items: list[SharedMediaItemDTO]
    has_next: bool
    next_cursor: str | None = None

class UploadSlotDTO(BaseModel):
    upload_token: UUID
    upload_url: str
    attachment_type: AttachmentType
    expires_in: int

