from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Self
from uuid import UUID, uuid7

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    Boolean,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.chats.config import chat_config
from app.chats.exceptions import (
    AttachmentLimitExceededError,
    AttachmentNotFoundError,
    InvalidMessageError,
    MessageTooLongError,
)
from app.chats.models.attachment import AttachmentStatus, AttachmentType, MessageAttachment
from app.chats.models.profile import ChatUserProfile
from app.core.db.base_model import BaseModel, DateMixin
from app.core.events.event import BaseEvent

if TYPE_CHECKING:
    from app.chats.models.chat import Chat


class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    SYSTEM = "system"
    REPLY = "reply"
    FORWARD = "forward"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"


@dataclass(frozen=True)
class SendedMessageEvent(BaseEvent):
    message_id: str
    chat_id: str
    seq: int
    sender_id: int | None
    message_type: str

    __event_name__ = "chats.message.sent"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class ReadedMessageEvent(BaseEvent):
    chat_id: str
    seq: int
    reader_id: int

    __event_name__ = "chats.message.readed"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class ModifiedMessageEvent(BaseEvent):
    message_id: str
    chat_id: str
    seq: int
    modified_by: int

    __event_name__ = "chats.message.modified"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


@dataclass(frozen=True)
class DeletedMessageEvent(BaseEvent):
    message_id: str
    chat_id: str
    seq: int
    deleted_by: int

    __event_name__ = "chats.message.deleted"

    def get_partition_key(self) -> str:
        return str(self.chat_id)


class Message(BaseModel, DateMixin):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(SAUUID(as_uuid=True), nullable=False, primary_key=True)

    chat_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(BigInteger, default=0)

    author_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    type: Mapped[MessageType] = mapped_column(
        SAEnum(MessageType), default=MessageType.TEXT, nullable=False
    )
    content: Mapped[str | None] = mapped_column(String(chat_config.MAX_MESSAGE_LENGTH))

    reply_to_id: Mapped[UUID | None] = mapped_column(
        SAUUID, ForeignKey("messages.id"), nullable=True
    )

    forwarded_from_chat_id: Mapped[UUID | None] = mapped_column(
        SAUUID, ForeignKey("chats.id", ondelete="SET NULL"), nullable=True
    )
    forwarded_from_message_id: Mapped[UUID | None] = mapped_column(
        SAUUID, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    forwarded_from_author_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    chat: Mapped[Chat] = relationship(back_populates="messages", foreign_keys=[chat_id], lazy="noload")
    reply_to: Mapped[Message | None] = relationship(
        foreign_keys=[reply_to_id], remote_side="Message.id", lazy="noload"
    )
    forwarded_from: Mapped[Message | None] = relationship(
        foreign_keys=[forwarded_from_message_id], remote_side="Message.id", lazy="noload"
    )
    attachments: Mapped[list[MessageAttachment]] = relationship(
        lazy="noload", cascade="all, delete-orphan"
    )
    profile: Mapped[ChatUserProfile | None] = relationship(
        ChatUserProfile,
        foreign_keys=[author_id],
        primaryjoin="Message.author_id == ChatUserProfile.user_id",
        lazy="noload",
    )


    __table_args__ = (
        Index("ix_messages_chat_not_deleted", "chat_id", "seq",
              postgresql_where="is_deleted = false"),
    )

    @classmethod
    def create(
        cls,
        sender_id: int | None,
        chat_id: UUID,
        seq: int,
        content: str | None,
        reply_to_id: UUID | None = None,
        message_type: MessageType = MessageType.TEXT,
        forwarded_from_chat_id: UUID | None = None,
        forwarded_from_message_id: UUID | None = None,
        forwarded_from_author_id: int | None=None,
        attachments: list[MessageAttachment] | None = None,
    ) -> Self:
        if message_type == MessageType.REPLY and reply_to_id is None:
            raise InvalidMessageError(reason="reply_to_id is required for reply messages")

        instance = cls(
            id=uuid7(),
            author_id=sender_id,
            chat_id=chat_id,
            seq=seq,
            content=content,
            reply_to_id=reply_to_id,
            type=message_type,
            forwarded_from_chat_id=forwarded_from_chat_id,
            forwarded_from_message_id=forwarded_from_message_id,
            forwarded_from_author_id=forwarded_from_author_id,
        )

        instance.validate_content()

        if attachments is not None:
            instance.attachments.extend(attachments)

        if attachments is not None or message_type in (
            MessageType.VOICE, MessageType.VIDEO_NOTE
        ):
            instance.validate_attachments()

        instance.register_event(SendedMessageEvent(
            message_id=str(instance.id),
            chat_id=str(instance.chat_id),
            seq=instance.seq,
            sender_id=instance.author_id,
            message_type=message_type.value
        ))

        return instance

    def update_content(self, new_content: str, modified_by: int) -> None:
        self.content = new_content
        self.is_edited = True
        self.validate_content()
        self.register_event(
            ModifiedMessageEvent(
                message_id=str(self.id),
                chat_id=str(self.chat_id),
                seq=self.seq,
                modified_by=modified_by
            )
        )

    def delete(self, deleted_by: int) -> None:
        self.is_deleted = True
        self.register_event(
            DeletedMessageEvent(
                message_id=str(self.id),
                chat_id=str(self.chat_id),
                seq=self.seq,
                deleted_by=deleted_by
            )
        )

    def validate_content(self) -> None:
        if not self.content:
            return

        if len(self.content) > chat_config.MAX_MESSAGE_LENGTH:
            raise MessageTooLongError(
                length=len(self.content),
                max_length=chat_config.MAX_MESSAGE_LENGTH
            )

        if "\x00" in self.content:
            raise InvalidMessageError(reason="message content contains null byte")

    def validate_attachments(self) -> None:
        media_count = sum(
            1 for a in self.attachments if a.attachment_type in (AttachmentType.IMAGE, AttachmentType.VIDEO)
        )
        file_count = sum(1 for a in self.attachments if a.attachment_type == AttachmentType.FILE)
        voice_count = sum(1 for a in self.attachments if a.attachment_type == AttachmentType.VOICE)
        video_note_count = sum(
            1 for a in self.attachments if a.attachment_type == AttachmentType.VIDEO_NOTE
        )
        exclusive_count = voice_count + video_note_count

        success = all(a.attachment_status == AttachmentStatus.SUCCESS for a in self.attachments)

        if media_count > chat_config.MAX_MEDIA_PER_MESSAGE:
            raise AttachmentLimitExceededError(count=media_count)
        if file_count > chat_config.MAX_FILES_PER_MESSAGE:
            raise AttachmentLimitExceededError(count=file_count)

        if exclusive_count > 1:
            raise AttachmentLimitExceededError(count=exclusive_count)
        if exclusive_count and (media_count or file_count):
            raise AttachmentLimitExceededError(
                count=exclusive_count + media_count + file_count
            )

        if self.type == MessageType.VOICE and voice_count != 1:
            raise InvalidMessageError(
                reason="voice message requires exactly one voice attachment"
            )
        if self.type == MessageType.VIDEO_NOTE and video_note_count != 1:
            raise InvalidMessageError(
                reason="video_note message requires exactly one video_note attachment"
            )
        if exclusive_count and self.type not in (
            MessageType.VOICE, MessageType.VIDEO_NOTE, MessageType.FORWARD
        ):
            raise InvalidMessageError(
                reason="voice/video_note attachment requires matching message_type"
            )

        if success is False:
            raise AttachmentNotFoundError(attachment_id="")
