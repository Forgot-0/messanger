from uuid import uuid4

import pytest

from app.chats.models.attachment import AttachmentStatus, AttachmentType, MessageAttachment


def make_attachment(
    att_type: AttachmentType = AttachmentType.IMAGE,
    *,
    chat_id=None,
    uploader_id: int = 1,
    mime_type: str = "image/jpeg",
    original_filename: str = "photo.jpg",
    size: int = 1024,
    s3_key: str = "chats/abc/123/photo.jpg",
) -> MessageAttachment:
    return MessageAttachment.create(
        chat_id=chat_id or uuid4(),
        uploader_id=uploader_id,
        attachment_type=att_type,
        s3_key=s3_key,
        mime_type=mime_type,
        original_filename=original_filename,
        size=size,
    )


@pytest.mark.unit
@pytest.mark.chats
class TestMessageAttachmentCreate:

    def test_initial_status_is_pending(self) -> None:
        att = make_attachment()
        assert att.attachment_status == AttachmentStatus.PENDING

    def test_message_id_is_none_on_create(self) -> None:
        att = make_attachment()
        assert att.message_id is None

    def test_id_is_set_on_create(self) -> None:
        att = make_attachment()
        assert att.id is not None

    def test_fields_are_stored_correctly(self) -> None:
        chat_id = uuid4()
        att = make_attachment(
            AttachmentType.FILE,
            chat_id=chat_id,
            uploader_id=42,
            mime_type="application/pdf",
            original_filename="report.pdf",
            size=204800,
            s3_key="chats/x/y/report.pdf",
        )
        assert att.attachment_type == AttachmentType.FILE
        assert att.chat_id == chat_id
        assert att.uploader_id == 42
        assert att.mime_type == "application/pdf"
        assert att.original_filename == "report.pdf"
        assert att.size == 204800
        assert att.s3_key == "chats/x/y/report.pdf"

    def test_width_height_duration_are_none_on_create(self) -> None:
        att = make_attachment()
        assert att.width is None
        assert att.height is None
        assert att.duration_seconds is None


@pytest.mark.unit
@pytest.mark.chats
class TestMarkProcessed:

    def test_mark_proccesed_sets_success_status(self) -> None:
        att = make_attachment()
        assert att.attachment_status == AttachmentStatus.PENDING
        att.mark_proccesed()
        assert att.attachment_status == AttachmentStatus.SUCCESS

    def test_mark_proccesed_is_idempotent(self) -> None:
        att = make_attachment()
        att.mark_proccesed()
        att.mark_proccesed()
        assert att.attachment_status == AttachmentStatus.SUCCESS

    def test_error_attachment_can_be_marked_processed(self) -> None:
        att = make_attachment()
        att.attachment_status = AttachmentStatus.ERROR
        att.mark_proccesed()
        assert att.attachment_status == AttachmentStatus.SUCCESS


@pytest.mark.unit
@pytest.mark.chats
class TestDimensionSetters:

    @pytest.mark.parametrize("w,h", [(0, 0), (1, 1), (1920, 1080), (4096, 2160), (720, 1280)])
    def test_set_resolution_stores_both_dimensions(self, w: int, h: int) -> None:
        att = make_attachment(AttachmentType.IMAGE)
        att.set_resolution(w, h)
        assert (att.width, att.height) == (w, h)

    @pytest.mark.parametrize("seconds", [0, 1, 30, 3600, 7200])
    def test_set_duration_stores_seconds(self, seconds: int) -> None:
        att = make_attachment(AttachmentType.VIDEO)
        att.set_duration(seconds)
        assert att.duration_seconds == seconds


@pytest.mark.unit
@pytest.mark.chats
class TestCreateForForward:

    @pytest.mark.parametrize("att_type", [AttachmentType.IMAGE, AttachmentType.VIDEO, AttachmentType.FILE])
    def test_forward_copies_payload_into_target_chat(self, att_type: AttachmentType) -> None:
        original = make_attachment(
            att_type,
            uploader_id=99,
            mime_type="image/png",
            original_filename="screenshot.png",
            size=512000,
            s3_key="chats/orig/abc/photo.jpg",
        )
        target_chat_id = uuid4()

        forwarded = original.create_for_forward(chat_id=target_chat_id)

        assert forwarded.chat_id == target_chat_id
        assert forwarded.attachment_type == att_type
        assert forwarded.uploader_id == 99
        assert forwarded.mime_type == "image/png"
        assert forwarded.original_filename == "screenshot.png"
        assert forwarded.size == 512000
        assert forwarded.s3_key == "chats/orig/abc/photo.jpg"

    def test_forward_is_a_fresh_row_ready_for_a_new_message(self) -> None:
        original = make_attachment()
        original.attachment_status = AttachmentStatus.PENDING
        original.message_id = uuid4()

        forwarded = original.create_for_forward(chat_id=uuid4())

        assert forwarded.id != original.id
        assert forwarded.source_attachment_id == original.id
        assert forwarded.message_id is None
        assert forwarded.attachment_status == AttachmentStatus.SUCCESS

    def test_original_is_not_mutated_by_forward(self) -> None:
        original = make_attachment()
        original_id = original.id
        original_status = original.attachment_status
        original_chat = original.chat_id

        original.create_for_forward(chat_id=uuid4())

        assert original.id == original_id
        assert original.attachment_status == original_status
        assert original.chat_id == original_chat
