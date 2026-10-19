from enum import StrEnum

from pydantic import BaseModel, Field


class WSEventType(StrEnum):
    NEW_MESSAGE = "new_message"
    MESSAGE_DELETED = "message_deleted"
    MESSAGE_EDITED = "message_edited"
    MESSAGES_READ = "messages_read"
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    MEMBER_KICK = "member_kick"
    MEMBER_BANNED = "member_banned"
    MEMBER_MUTED = "member_muted"
    MESSAGE_PINNED = "message_pinned"
    MESSAGE_UNPINNED = "message_unpinned"
    JOIN_REQUEST_CREATED = "join_request_created"
    JOIN_REQUEST_APPROVED = "join_request_approved"
    JOIN_REQUEST_DECLINED = "join_request_declined"
    JOIN_REQUEST_CANCELLED = "join_request_cancelled"
    TYPING_START = "typing_start"
    TYPING_STOP = "typing_stop"
    PING = "ping"

    REACTION_UPDATED = "reaction_update"

    ATTACHMENT_SUCCESS = "attachment_success"

    CHAT_CREATED = "chat_created"
    CHAT_UPDATED = "chat_updated"
    CHAT_DELETED = "chat_deleted"
    CHAT_OWNERSHIP_TRANSFERRED = "chat_ownership_transferred"

    CALL_STARTED = "call_started"
    CALL_ENDED = "call_ended"
    CALL_JOINED = "call_joined"
    CALL_LEFT = "call_left"


class WSClientOp(StrEnum):
    PING = "ping"
    PONG = "pong"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    RESUME = "resume"
    TYPING = "typing"


class TypingAction(StrEnum):
    TYPING = "typing"
    RECORD_VOICE = "record_voice"
    UPLOAD_VOICE = "upload_voice"
    RECORD_VIDEO_NOTE = "record_video_note"
    UPLOAD_VIDEO_NOTE = "upload_video_note"
    UPLOAD_PHOTO = "upload_photo"
    UPLOAD_VIDEO = "upload_video"
    UPLOAD_FILE = "upload_file"
    CANCEL = "cancel"


class WSClientCommand(BaseModel):
    op: WSClientOp
    chat_id: str | None = None
    last_seq: int | None = None
    cursors: dict[str, int] = Field(default_factory=dict)
    action: TypingAction = TypingAction.TYPING


class AttachmentSuccessPayload(BaseModel):
    user_id: int
    chat_id: str
    tokens: list[str]

