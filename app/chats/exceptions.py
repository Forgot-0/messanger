from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.chats.config import chat_config
from app.core.exceptions import ApplicationError


@dataclass(kw_only=True)
class NotFoundChatError(ApplicationError):
    chat_id: str
    code: str = "NOT_FOUND_CHAT"
    status: int = 404

    @property
    def message(self) -> str:
        return "Chat not found"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id}


@dataclass(kw_only=True)
class NotChatMemberError(ApplicationError):
    chat_id: str
    user_id: int
    code: str = "NOT_CHAT_MEMBER"
    status: int = 403

    @property
    def message(self) -> str:
        return "You are not a member of this chat"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "user_id": self.user_id}


@dataclass(kw_only=True)
class NotFoundMessageError(ApplicationError):
    message_id: str
    code: str = "NOT_FOUND_MESSAGE"
    status: int = 404

    @property
    def message(self) -> str:
        return "Message not found"

    @property
    def detail(self) -> dict:
        return {"message_id": self.message_id}


@dataclass(kw_only=True)
class AccessDeniedChatError(ApplicationError):
    chat_id: str
    requester_id: int

    code: str = "CHAT_ACCESS_DENIED"
    status: int = 403

    @property
    def message(self) -> str:
        return "Insufficient chat permissions"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "requester_id": self.requester_id}


@dataclass(kw_only=True)
class SlowModeOutOfRangeError(ApplicationError):
    seconds: int
    code: str = "SLOW_MODE_OUT_OF_RANGE"
    status: int = 400

    @property
    def message(self) -> str:
        return "slow_mode_seconds is out of allowed range"

    @property
    def detail(self) -> dict:
        return {"seconds": self.seconds, "valid_range": [0, chat_config.MAX_SLOW_MODE_SECONDS]}


@dataclass(kw_only=True)
class SlowModeLimitError(ApplicationError):
    chat_id: str
    retry_after: int
    code: str = "SLOW_MODE_LIMIT"
    status: int = 429

    @property
    def message(self) -> str:
        return "Slow mode is enabled for this chat"

    @property
    def detail(self) -> dict[str, Any]:
        return {"chat_id": self.chat_id, "retry_after": self.retry_after}


@dataclass(kw_only=True)
class AlreadyMemberError(ApplicationError):
    user_id: int
    chat_id: str
    code: str = "ALREADY_CHAT_MEMBER"
    status: int = 409

    @property
    def message(self) -> str:
        return "User is already a member of this chat"

    @property
    def detail(self) -> dict:
        return {"user_id": self.user_id, "chat_id": self.chat_id}


@dataclass(kw_only=True)
class TooLongChatRoleNameError(ApplicationError):
    role_name: str
    code: str = "TOO_LONG_CHAT_ROLE_NAME"
    status: int = 400

    @property
    def message(self) -> str:
        return "Too long chat role name"

    @property
    def detail(self) -> dict:
        return {"role_name": self.role_name, "max_len": 32}


@dataclass(kw_only=True)
class DirectChatAlreadyExistsError(ApplicationError):
    chat_id: str
    code: str = "DIRECT_CHAT_EXISTS"
    status: int = 409

    @property
    def message(self) -> str:
        return "Direct chat already exists"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id}


@dataclass(kw_only=True)
class MemberLimitExceededError(ApplicationError):
    limit: int
    code: str = "MEMBER_LIMIT_EXCEEDED"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Chat member limit reached ({self.limit})"

    @property
    def detail(self) -> dict:
        return {"limit": self.limit}


@dataclass(kw_only=True)
class MessageTooLongError(ApplicationError):
    length: int
    max_length: int
    code: str = "MESSAGE_TOO_LONG"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Message exceeds max length of {self.max_length}"

    @property
    def detail(self) -> dict:
        return {"length": self.length, "max_length": self.max_length}


@dataclass(kw_only=True)
class LiveKitServiceError(ApplicationError):
    reason: str
    code: str = "LIVEKIT_ERROR"
    status: int = 502

    @property
    def message(self) -> str:
        return "LiveKit service error"

    @property
    def detail(self) -> dict[str, Any]:
        return {"reason": self.reason}


@dataclass(kw_only=True)
class LiveKitUnauthorizedError(ApplicationError):
    code: str = "LIVEKIT_UNAUTHORIZED"
    status: int = 502

    @property
    def message(self) -> str:
        return "LiveKit unauthorized"

    @property
    def detail(self) -> dict[str, Any]:
        return {}


@dataclass(kw_only=True)
class NoActiveCallError(ApplicationError):
    chat_id: str
    code: str = "NO_ACTIVE_CALL"
    status: int = 404

    @property
    def message(self) -> str:
        return "There is no active call in this chat"

    @property
    def detail(self) -> dict[str, Any]:
        return {"chat_id": self.chat_id}


@dataclass(kw_only=True)
class ActiveCallExistsError(ApplicationError):
    chat_id: str
    code: str = "ACTIVE_CALL_EXISTS"
    status: int = 409

    @property
    def message(self) -> str:
        return "A call is already active in this chat"

    @property
    def detail(self) -> dict[str, Any]:
        return {"chat_id": self.chat_id}


@dataclass(kw_only=True)
class AttachmentValidationError(ApplicationError):
    mime_type: str
    code: str = "ATTACHMENT_VALIDATION"
    status: int = 400

    @property
    def message(self) -> str:
        return "Attachment validation failed"

    @property
    def detail(self) -> dict[str, Any]:
        return {"mime_type": self.mime_type}


class AttachmentRejectionReason(StrEnum):
    MIME_MISMATCH = "mime_mismatch"
    SIZE_LIMIT_EXCEEDED = "size_limit_exceeded"
    DURATION_LIMIT_EXCEEDED = "duration_limit_exceeded"
    RESOLUTION_LIMIT_EXCEEDED = "resolution_limit_exceeded"
    FRAME_RATE_LIMIT_EXCEEDED = "frame_rate_limit_exceeded"
    METADATA_UNREADABLE = "metadata_unreadable"
    PROBE_TIMEOUT = "probe_timeout"
    INVALID_MEDIA = "invalid_media"


@dataclass(kw_only=True)
class AttachmentMediaValidationError(ApplicationError):
    reason: AttachmentRejectionReason
    attachment_id: str
    attachment_type: str
    limit: int | None = None
    detected: dict[str, Any] | None = None

    code: str = "ATTACHMENT_MEDIA_VALIDATION"
    status: int = 400

    @property
    def message(self) -> str:
        return "Attachment media validation failed"

    @property
    def detail(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "attachment_id": self.attachment_id,
            "attachment_type": self.attachment_type,
            "reason": self.reason.value,
        }
        if self.limit is not None:
            payload["limit"] = self.limit
        if self.detected:
            payload.update(self.detected)
        return payload


@dataclass(kw_only=True)
class InvalidUploadTokenError(ApplicationError):
    token: str
    code: str = "INVALID_UPLOAD_TOKEN"
    status: int = 400

    @property
    def message(self) -> str:
        return "Upload token is invalid, expired, or does not belong to this chat"

    @property
    def detail(self) -> dict[str, Any]:
        return {"token": self.token}


@dataclass(kw_only=True)
class AttachmentLimitExceededError(ApplicationError):
    count: int
    code: str = "ATTACHMENT_LIMIT_EXCEEDED"
    status: int = 400

    @property
    def message(self) -> str:
        return "Attachment limit exceeded"

    @property
    def detail(self) -> dict[str, Any]:
        return {"count": self.count}


@dataclass(kw_only=True)
class AttachmentNotFoundError(ApplicationError):
    attachment_id: str
    code: str = "ATTACHMENT_NOT_FOUND"
    status: int = 404

    @property
    def message(self) -> str:
        return "Attachment not found"

    @property
    def detail(self) -> dict[str, Any]:
        return {"attachment_id": self.attachment_id}


@dataclass(kw_only=True)
class InvalidMessageError(ApplicationError):
    reason: str
    code: str = "INVALID_MESSAGE"
    status: int = 400

    @property
    def message(self) -> str:
        return "Invalid message payload"

    @property
    def detail(self) -> dict[str, Any]:
        return {"reason": self.reason}


@dataclass(kw_only=True)
class EmptyAttachmentUploadRequestError(ApplicationError):
    code: str = "EMPTY_ATTACHMENT_UPLOAD_REQUEST"
    status: int = 400

    @property
    def message(self) -> str:
        return "At least one attachment upload must be requested"

    @property
    def detail(self) -> dict[str, Any]:
        return {}


@dataclass(kw_only=True)
class MaxLimitCursorError(ApplicationError):
    max_len: int
    current_len: int

    code: str = "MAX_LIMIT_CURSOR"
    status: int = 429

    @property
    def message(self) -> str:
        return "Max limit cursor"

    @property
    def detail(self) -> dict:
        return {
            "max": self.max_len,
            "current": self.current_len
        }

@dataclass(kw_only=True)
class InvalidReactionError(ApplicationError):
    emoji: str

    code: str = "INVALID_REACTION"
    status: int = 400

    @property
    def message(self) -> str:
        return "Reaction is not valid"

    @property
    def detail(self) -> dict:
        return {
            "emoji": self.emoji,
        }

@dataclass(kw_only=True)
class TooManyReactionsError(ApplicationError):
    limit: int
    scope: str = "message"
    code: str = "TOO_MANY_REACTIONS"
    status: int = 400

    @property
    def message(self) -> str:
        return "Too many reactions"

    @property
    def detail(self) -> dict:
        return {"limit": self.limit, "scope": self.scope}


@dataclass(kw_only=True)
class ReactionsDisabledError(ApplicationError):
    chat_id: str
    code: str = "REACTIONS_DISABLED"
    status: int = 403

    @property
    def message(self) -> str:
        return "Reactions are disabled in this chat"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id}


@dataclass(kw_only=True)
class ReactionNotAllowedError(ApplicationError):
    emoji: str
    allowed: list[str]
    code: str = "REACTION_NOT_ALLOWED"
    status: int = 400

    @property
    def message(self) -> str:
        return "This reaction is not allowed in this chat"

    @property
    def detail(self) -> dict:
        return {"emoji": self.emoji, "allowed": self.allowed}


@dataclass(kw_only=True)
class InvalidChatRoleError(ApplicationError):
    role_id: int
    code: str = "INVALID_CHAT_ROLE"
    status: int = 422

    @property
    def message(self) -> str:
        return "Unknown chat role"

    @property
    def detail(self) -> dict:
        return {"role_id": self.role_id}


@dataclass(kw_only=True)
class PinnedChatsLimitExceededError(ApplicationError):
    limit: int = chat_config.MAX_PINNED_CHATS

    code: str = "PINNED_CHATS_LIMIT_EXCEEDED"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Pinned chats limit reached ({self.limit})"

    @property
    def detail(self) -> dict:
        return {"limit": self.limit}


@dataclass(kw_only=True)
class InvalidChatUsernameError(ApplicationError):
    username: str
    reason: str
    code: str = "INVALID_CHAT_USERNAME"
    status: int = 400

    @property
    def message(self) -> str:
        return "Chat username is invalid"

    @property
    def detail(self) -> dict:
        return {"username": self.username, "reason": self.reason}


@dataclass(kw_only=True)
class ChatUsernameTakenError(ApplicationError):
    username: str
    code: str = "CHAT_USERNAME_TAKEN"
    status: int = 409

    @property
    def message(self) -> str:
        return "Chat username is already taken"

    @property
    def detail(self) -> dict:
        return {"username": self.username}


@dataclass(kw_only=True)
class ChatUsernameNotAllowedError(ApplicationError):
    chat_id: str
    reason: str
    code: str = "CHAT_USERNAME_NOT_ALLOWED"
    status: int = 400

    @property
    def message(self) -> str:
        return "This chat cannot have a public username"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "reason": self.reason}


@dataclass(kw_only=True)
class NotFoundChatUsernameError(ApplicationError):
    username: str
    code: str = "NOT_FOUND_CHAT_USERNAME"
    status: int = 404

    @property
    def message(self) -> str:
        return "Public chat with this username not found"

    @property
    def detail(self) -> dict:
        return {"username": self.username}


@dataclass(kw_only=True)
class InvalidOwnershipTransferError(ApplicationError):
    chat_id: str
    reason: str
    code: str = "INVALID_OWNERSHIP_TRANSFER"
    status: int = 400

    @property
    def message(self) -> str:
        return "Chat ownership cannot be transferred"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "reason": self.reason}


@dataclass(kw_only=True)
class NotFoundInviteLinkError(ApplicationError):
    invite: str
    code: str = "NOT_FOUND_INVITE_LINK"
    status: int = 404

    @property
    def message(self) -> str:
        return "Invite link not found"

    @property
    def detail(self) -> dict:
        return {"invite": self.invite}


class InviteLinkInactiveReason(StrEnum):
    EXPIRED = "expired"
    REVOKED = "revoked"
    USAGE_LIMIT_REACHED = "usage_limit_reached"


@dataclass(kw_only=True)
class InviteLinkExpiredError(ApplicationError):
    reason: InviteLinkInactiveReason
    code: str = "INVITE_LINK_EXPIRED"
    status: int = 410

    @property
    def message(self) -> str:
        return "Invite link is no longer active"

    @property
    def detail(self) -> dict:
        return {"reason": self.reason.value}


@dataclass(kw_only=True)
class InvalidInviteLinkError(ApplicationError):
    reason: str
    code: str = "INVALID_INVITE_LINK"
    status: int = 400

    @property
    def message(self) -> str:
        return "Invite link parameters are invalid"

    @property
    def detail(self) -> dict:
        return {"reason": self.reason}


@dataclass(kw_only=True)
class InviteLinksLimitExceededError(ApplicationError):
    limit: int = chat_config.MAX_INVITE_LINKS_PER_CHAT
    code: str = "INVITE_LINKS_LIMIT_EXCEEDED"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Invite links limit reached ({self.limit})"

    @property
    def detail(self) -> dict:
        return {"limit": self.limit}


@dataclass(kw_only=True)
class ChatAvatarValidationError(ApplicationError):
    reason: str
    mime_type: str | None = None
    file_size: int | None = None
    code: str = "CHAT_AVATAR_VALIDATION"
    status: int = 400

    @property
    def message(self) -> str:
        return "Chat avatar validation failed"

    @property
    def detail(self) -> dict[str, Any]:
        return {"reason": self.reason, "mime_type": self.mime_type, "file_size": self.file_size}


@dataclass(kw_only=True)
class UserBlockedError(ApplicationError):
    chat_id: str | None
    user_id: int
    code: str = "USER_BLOCKED"
    status: int = 403

    @property
    def message(self) -> str:
        return "Conversation is blocked by one of the participants"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "user_id": self.user_id}


@dataclass(kw_only=True)
class MessagesPrivacyRestrictedError(ApplicationError):
    chat_id: str | None
    user_id: int
    code: str = "MESSAGES_PRIVACY_RESTRICTED"
    status: int = 403

    @property
    def message(self) -> str:
        return "Privacy settings of this user do not allow messages from you"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "user_id": self.user_id}


@dataclass(kw_only=True)
class CallsPrivacyRestrictedError(ApplicationError):
    chat_id: str | None
    user_id: int
    code: str = "CALLS_PRIVACY_RESTRICTED"
    status: int = 403

    @property
    def message(self) -> str:
        return "Privacy settings of this user do not allow calls from you"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "user_id": self.user_id}


@dataclass(kw_only=True)
class UserPrivacyRestrictedError(ApplicationError):
    user_ids: list[int]
    code: str = "USER_PRIVACY_RESTRICTED"
    status: int = 403

    @property
    def message(self) -> str:
        return "Privacy settings of these users do not allow this action"

    @property
    def detail(self) -> dict:
        return {"user_ids": self.user_ids}


@dataclass(kw_only=True)
class PinnedMessagesLimitExceededError(ApplicationError):
    chat_id: str
    limit: int = chat_config.MAX_PINNED_MESSAGES
    code: str = "PINNED_MESSAGES_LIMIT_EXCEEDED"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Pinned messages limit reached ({self.limit})"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "limit": self.limit}


@dataclass(kw_only=True)
class SlowModeMultipleMessagesError(ApplicationError):
    chat_id: str
    count: int
    code: str = "SLOW_MODE_MULTIPLE_MESSAGES"
    status: int = 400

    @property
    def message(self) -> str:
        return "Slow mode is enabled, only one message can be sent at a time"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "count": self.count}


class ReadReceiptsUnavailableReason(StrEnum):
    CHAT_TYPE = "chat_type"
    CHAT_TOO_LARGE = "chat_too_large"
    MESSAGE_TOO_OLD = "message_too_old"


@dataclass(kw_only=True)
class ReadReceiptsUnavailableError(ApplicationError):
    chat_id: str
    reason: ReadReceiptsUnavailableReason
    code: str = "READ_RECEIPTS_UNAVAILABLE"
    status: int = 400

    @property
    def message(self) -> str:
        return "Read receipts are not available for this message"

    @property
    def detail(self) -> dict:
        return {
            "chat_id": self.chat_id,
            "reason": self.reason.value,
            "max_members": chat_config.READ_MARKS_MAX_MEMBERS,
            "retention_days": chat_config.READ_MARKS_RETENTION_DAYS,
        }


@dataclass(kw_only=True)
class NotFoundJoinRequestError(ApplicationError):
    chat_id: str
    user_id: int
    code: str = "NOT_FOUND_JOIN_REQUEST"
    status: int = 404

    @property
    def message(self) -> str:
        return "Join request not found"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "user_id": self.user_id}


@dataclass(kw_only=True)
class JoinRequestPendingError(ApplicationError):
    chat_id: str
    user_id: int
    code: str = "JOIN_REQUEST_PENDING"
    status: int = 409

    @property
    def message(self) -> str:
        return "Join request is already waiting for approval"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "user_id": self.user_id}


@dataclass(kw_only=True)
class JoinRequestNotPendingError(ApplicationError):
    chat_id: str
    user_id: int
    status_value: str
    code: str = "JOIN_REQUEST_NOT_PENDING"
    status: int = 409

    @property
    def message(self) -> str:
        return "Join request is already resolved"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "user_id": self.user_id, "status": self.status_value}


@dataclass(kw_only=True)
class JoinRequestRetryLaterError(ApplicationError):
    chat_id: str
    user_id: int
    retry_after: int
    code: str = "JOIN_REQUEST_RETRY_LATER"
    status: int = 429

    @property
    def message(self) -> str:
        return "Previous join request was declined, try again later"

    @property
    def detail(self) -> dict[str, Any]:
        return {"chat_id": self.chat_id, "user_id": self.user_id, "retry_after": self.retry_after}


@dataclass(kw_only=True)
class JoinRequestsLimitExceededError(ApplicationError):
    chat_id: str
    limit: int = chat_config.MAX_PENDING_JOIN_REQUESTS
    code: str = "JOIN_REQUESTS_LIMIT_EXCEEDED"
    status: int = 400

    @property
    def message(self) -> str:
        return f"Pending join requests limit reached ({self.limit})"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "limit": self.limit}


@dataclass(kw_only=True)
class JoinRequestNotAllowedError(ApplicationError):
    chat_id: str
    reason: str
    code: str = "JOIN_REQUEST_NOT_ALLOWED"
    status: int = 400

    @property
    def message(self) -> str:
        return "This chat does not accept join requests"

    @property
    def detail(self) -> dict:
        return {"chat_id": self.chat_id, "reason": self.reason}
