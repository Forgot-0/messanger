from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.chats.config import chat_config
from app.chats.models.attachment import AttachmentType
from app.chats.models.chat import ChatReactionsMode, ChatType
from app.chats.models.chat_roles import ChatRoleId
from app.chats.models.message import MessageType


class ClientMessageType(StrEnum):
    TEXT = MessageType.TEXT
    IMAGE = MessageType.IMAGE
    FILE = MessageType.FILE
    REPLY = MessageType.REPLY
    VOICE = MessageType.VOICE
    VIDEO_NOTE = MessageType.VIDEO_NOTE


class CreateChatRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    chat_type: ChatType = ChatType.DIRECT
    member_ids: list[int] = Field(default_factory=list, max_length=chat_config.MAX_BULK_ADD_MEMBERS)
    is_public: bool = False
    admin_only: bool = False
    slow_mode_seconds: int = Field(default=0, ge=0, le=chat_config.MAX_SLOW_MODE_SECONDS)
    permissions: dict[str, bool] = Field(default_factory=dict)


class UpdateChatRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    is_public: bool | None = None
    admin_only: bool | None = None
    slow_mode_seconds: int | None = Field(default=None, ge=0, le=chat_config.MAX_SLOW_MODE_SECONDS)
    permissions: dict[str, bool] | None = None
    reactions_mode: ChatReactionsMode | None = None
    allowed_reactions: list[str] | None = Field(
        default=None, max_length=chat_config.MAX_DISTINCT_REACTIONS_PER_MESSAGE
    )


class GetListUserChatsRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)
    last_chat_id: UUID | None = Field(None)
    last_activity_at: datetime | None =  Field(None)



class AddMemberRequest(BaseModel):
    user_id: int = Field(gt=0)
    role_id: ChatRoleId = ChatRoleId.MEMBER


class ChangeMemberRoleRequest(BaseModel):
    role_id: ChatRoleId


class BanMemberRequest(BaseModel):
    reason: str | None = None
    banned_to: datetime | None = None


class SendMessageRequest(BaseModel):
    content: str | None = Field(default=None, max_length=chat_config.MAX_MESSAGE_LENGTH)
    reply_to_id: UUID | None = None
    message_type: ClientMessageType = ClientMessageType.TEXT
    upload_tokens: list[UUID] = Field(default_factory=list)


class EditMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=chat_config.MAX_MESSAGE_LENGTH)


class ForwardMessageRequest(BaseModel):
    source_chat_id: UUID
    source_message_id: UUID
    comment: str | None = Field(default=None, max_length=chat_config.MAX_MESSAGE_LENGTH)


class MarkReadRequest(BaseModel):
    message_seq: int = Field(ge=0)


class SetReactionsRequest(BaseModel):
    reactions: list[str] = Field(
        default_factory=list,
        max_length=chat_config.MAX_REACTIONS_PER_USER_PER_MESSAGE,
    )


class UploadRequestItem(BaseModel):
    attachment_type: AttachmentType | None = Field(default=None)
    filename: str = Field(min_length=1, max_length=256)
    mime_type: str = Field(min_length=1, max_length=128)
    file_size: int = Field(gt=0, le=max(chat_config.MAX_FILE_SIZE, chat_config.MAX_MEDIA_SIZE))


class RequestAttachmentUploadRequest(BaseModel):
    uploads: list[UploadRequestItem] = Field(
        min_length=1,
        max_length=chat_config.MAX_MEDIA_PER_MESSAGE + chat_config.MAX_FILES_PER_MESSAGE
    )


class ConfirmAttachmentUploadRequest(BaseModel):
    upload_tokens: list[UUID] = Field(
        min_length=1,
        max_length=chat_config.MAX_MEDIA_PER_MESSAGE + chat_config.MAX_FILES_PER_MESSAGE
    )


class MuteParticipantRequest(BaseModel):
    muted: bool = True

