from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid7

from sqlalchemy import (
    UUID as SAUUID,
    BigInteger,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base_model import BaseModel, DateMixin


class AttachmentType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    FILE = "file"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"


class AttachmentStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    ERROR = "error"


class HlsStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class MessageAttachment(BaseModel, DateMixin):
    __tablename__ = "message_attachments"

    id: Mapped[UUID] = mapped_column(SAUUID(as_uuid=True), primary_key=True)
    message_id: Mapped[UUID | None] = mapped_column(
        SAUUID, ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    chat_id: Mapped[UUID] = mapped_column(SAUUID(as_uuid=True), nullable=False)

    uploader_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    attachment_type: Mapped[AttachmentType] = mapped_column(
        Enum(AttachmentType), nullable=False
    )
    attachment_status: Mapped[AttachmentStatus] = mapped_column(
        Enum(AttachmentStatus), nullable=False
    )

    s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(256), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_attachment_id: Mapped[UUID | None] = mapped_column(SAUUID(as_uuid=True), nullable=True)

    message_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    thumbhash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previews: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    hls_status: Mapped[HlsStatus | None] = mapped_column(
        Enum(HlsStatus, native_enum=False, length=16), nullable=True
    )
    hls_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hls_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        Index("ix_msg_attachments_chat_uploader", "chat_id", "uploader_id"),
        Index(
            "ix_msg_attachments_shared_media",
            "chat_id", "attachment_type", "message_seq", "id",
            postgresql_where=text("message_seq IS NOT NULL"),
        ),
        Index(
            "ix_msg_attachments_source",
            "source_attachment_id",
            postgresql_where=text("source_attachment_id IS NOT NULL"),
        ),
        Index(
            "ix_msg_attachments_hls_pending",
            "updated_at",
            postgresql_where=text("hls_status = 'PENDING'"),
        ),
    )

    @classmethod
    def create(
        cls, chat_id: UUID, uploader_id: int,
        attachment_type: AttachmentType, s3_key: str, mime_type: str,
        original_filename: str, size: int
    ) -> Self:
        instance = cls(
            id=uuid7(),
            chat_id=chat_id,
            message_id=None, uploader_id=uploader_id,
            attachment_type=attachment_type, s3_key=s3_key, mime_type=mime_type,
            original_filename=original_filename, size=size,
            attachment_status=AttachmentStatus.PENDING
        )
        return instance

    def create_for_forward(self, chat_id: UUID) -> MessageAttachment:
        instance = MessageAttachment(
            id=uuid7(),
            chat_id=chat_id,
            uploader_id=self.uploader_id,
            attachment_type=self.attachment_type, s3_key=self.s3_key, mime_type=self.mime_type,
            original_filename=self.original_filename, size=self.size,
            attachment_status=AttachmentStatus.SUCCESS,
            width=self.width, height=self.height, duration_seconds=self.duration_seconds,
            source_attachment_id=self.media_root_id,
            thumbhash=self.thumbhash,
            previews=list(self.previews) if self.previews else None,
            hls_status=self.hls_status,
            hls_key=self.hls_key,
        )
        return instance

    @property
    def media_root_id(self) -> UUID:
        """Вложение, под которое залиты байты. Пересылка пересылки указывает на корень,
        поэтому HLS, готовый позже пересылки, проставляется всем копиям одним UPDATE."""
        return self.source_attachment_id or self.id

    def bind_to_message(self, message_seq: int) -> None:
        self.message_seq = message_seq

    def apply_media(
        self,
        *,
        width: int | None,
        height: int | None,
        previews: list[dict[str, Any]],
        thumbhash: str | None,
    ) -> None:
        if width and height:
            self.set_resolution(width, height)
        self.previews = previews or None
        self.thumbhash = thumbhash

    def replace_original(self, *, mime_type: str, size: int, extension: str) -> None:
        if mime_type != self.mime_type:
            stem, dot, _ = self.original_filename.rpartition(".")
            stem = stem if dot and stem else self.original_filename
            self.original_filename = f"{stem[:255 - len(extension)]}.{extension}"
        self.mime_type = mime_type
        self.size = size

    def request_hls(self) -> None:
        self.hls_status = HlsStatus.PENDING
        self.hls_attempts = 0

    def start_hls_attempt(self) -> None:
        self.hls_attempts += 1

    def set_resolution(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def set_duration(self, duration_seconds: int) -> None:
        self.duration_seconds = duration_seconds

    def mark_proccesed(self) -> None:
        self.attachment_status = AttachmentStatus.SUCCESS

    def mark_error(self) -> None:
        self.attachment_status = AttachmentStatus.ERROR
