from uuid import uuid4

import pytest

from app.chats.config import chat_config
from app.chats.exceptions import (
    AttachmentLimitExceededError,
    InvalidMessageError,
    MessageTooLongError,
)
from app.chats.models.attachment import AttachmentStatus, AttachmentType, MessageAttachment
from app.chats.models.message import (
    DeletedMessageEvent,
    Message,
    MessageType,
    ModifiedMessageEvent,
    SendedMessageEvent,
)


def create_message(
    content: str | None = "hello",
    msg_type: MessageType = MessageType.TEXT,
    reply_to_id=None,
) -> Message:
    return Message.create(
        sender_id=1,
        chat_id=uuid4(),
        seq=1,
        content=content,
        message_type=msg_type,
        reply_to_id=reply_to_id,
    )


def create_attachment(
    att_type: AttachmentType = AttachmentType.IMAGE,
    status: AttachmentStatus = AttachmentStatus.SUCCESS,
) -> MessageAttachment:
    a = MessageAttachment.create(
        chat_id=uuid4(),
        uploader_id=1,
        attachment_type=att_type,
        s3_key="key",
        mime_type="image/jpeg",
        original_filename="img.jpg",
        size=1024,
    )
    a.attachment_status = status
    return a


@pytest.mark.unit
@pytest.mark.chats
class TestMessageModel:

    def test_create_text_message_registers_sent_event(self) -> None:
        msg = create_message("hello world")

        events = msg.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], SendedMessageEvent)
        assert events[0].seq == 1
        assert events[0].sender_id == 1
        assert events[0].message_type == MessageType.TEXT.value

    def test_content_is_stored_verbatim(self) -> None:
        # Экранирование — забота слоя отображения: в БД лежит то, что ввёл автор,
        # иначе правка сообщения экранирует его повторно (& -> &amp; -> &amp;amp;).
        raw = '<script>alert("xss")</script> 2 < 3 && 4 > 1'
        msg = create_message(raw)
        assert msg.content == raw

    def test_edit_does_not_mangle_content(self) -> None:
        msg = create_message("a & b")
        msg.update_content("a && b", modified_by=1)
        assert msg.content == "a && b"

    def test_content_too_long_raises(self) -> None:
        with pytest.raises(MessageTooLongError) as exc:
            create_message("x" * (chat_config.MAX_MESSAGE_LENGTH + 1))
        assert exc.value.max_length == chat_config.MAX_MESSAGE_LENGTH

    def test_null_byte_in_content_raises(self) -> None:
        with pytest.raises(InvalidMessageError):
            create_message("hello\x00world")

    def test_reply_without_reply_to_id_raises(self) -> None:
        with pytest.raises(InvalidMessageError) as exc:
            create_message(msg_type=MessageType.REPLY, reply_to_id=None)
        assert "reply_to_id" in exc.value.reason

    def test_reply_with_reply_to_id_succeeds(self) -> None:
        parent_id = uuid4()
        msg = create_message(msg_type=MessageType.REPLY, reply_to_id=parent_id)
        assert msg.reply_to_id == parent_id

    def test_system_message_skips_content_validation(self) -> None:
        msg = Message.create(
            sender_id=None,
            chat_id=uuid4(),
            seq=1,
            content="<b>user</b> joined",
            message_type=MessageType.SYSTEM,
        )
        assert msg.content == "<b>user</b> joined"

    def test_update_content_sets_edited_flag_and_registers_event(self) -> None:
        msg = create_message("original")
        msg.pull_events()

        msg.update_content("edited", modified_by=1)

        assert msg.content == "edited"
        assert msg.is_edited is True
        events = msg.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], ModifiedMessageEvent)
        assert events[0].modified_by == 1

    def test_delete_sets_flag_and_registers_event(self) -> None:
        msg = create_message("bye")
        msg.pull_events()

        msg.delete(deleted_by=1)

        assert msg.is_deleted is True
        events = msg.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], DeletedMessageEvent)
        assert events[0].deleted_by == 1

    def test_too_many_media_attachments_raises(self) -> None:
        attachments = [
            create_attachment(AttachmentType.IMAGE)
            for _ in range(chat_config.MAX_MEDIA_PER_MESSAGE + 1)
        ]
        with pytest.raises(AttachmentLimitExceededError):
            Message.create(
                sender_id=1,
                chat_id=uuid4(),
                seq=1,
                content="pics",
                attachments=attachments,
            )

    def test_too_many_file_attachments_raises(self) -> None:
        attachments = [
            create_attachment(AttachmentType.FILE)
            for _ in range(chat_config.MAX_FILES_PER_MESSAGE + 1)
        ]
        with pytest.raises(AttachmentLimitExceededError):
            Message.create(
                sender_id=1,
                chat_id=uuid4(),
                seq=1,
                content="files",
                attachments=attachments,
            )

    def test_pending_attachment_raises_not_found(self) -> None:
        from app.chats.exceptions import AttachmentNotFoundError
        pending = create_attachment(status=AttachmentStatus.PENDING)
        with pytest.raises(AttachmentNotFoundError):
            Message.create(
                sender_id=1,
                chat_id=uuid4(),
                seq=1,
                content="pending",
                attachments=[pending],
            )
