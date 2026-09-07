from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.chats.models.attachment import AttachmentStatus, AttachmentType


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

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AttachmentDownloadUrlDTO(BaseModel):
    attachment_id: UUID
    url: str
    expires_in: int

class UploadSlotDTO(BaseModel):
    upload_token: UUID
    upload_url: str
    attachment_type: AttachmentType
    expires_in: int

