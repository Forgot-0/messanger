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
    TYPING_START = "typing_start"
    TYPING_STOP = "typing_stop"
    PING = "ping"

    REACTION_UPDATED = "reaction_update"

    ATTACHMENT_SUCCESS = "attachment_success"

    CHAT_CREATED = "chat_created"
    CHAT_UPDATED = "chat_updated"
    CHAT_DELETED = "chat_deleted"

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


class WSClientCommand(BaseModel):
    op: WSClientOp
    chat_id: str | None = None
    last_seq: int | None = None
    cursors: dict[str, int] = Field(default_factory=dict)


class AttachmentSuccessPayload(BaseModel):
    user_id: int
    chat_id: str
    tokens: list[str]

