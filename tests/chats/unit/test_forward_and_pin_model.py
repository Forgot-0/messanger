from uuid import uuid4, uuid7

import pytest

from app.chats.config import chat_config
from app.chats.exceptions import (
    InvalidMessageError,
    NotFoundMessageError,
    PinnedMessagesLimitExceededError,
)
from app.chats.models.attachment import AttachmentStatus, AttachmentType, MessageAttachment
from app.chats.models.chat import Chat, ChatType
from app.chats.models.message import (
    Message,
    MessageType,
    PinnedMessageEvent,
    SendedMessageEvent,
    SystemMessageAction,
    UnpinnedMessagesEvent,
)


def make_attachment(
    attachment_type: AttachmentType = AttachmentType.IMAGE,
    status: AttachmentStatus = AttachmentStatus.SUCCESS,
    width: int | None = 1280,
    height: int | None = 720,
) -> MessageAttachment:
    attachment = MessageAttachment.create(
        chat_id=uuid4(),
        uploader_id=7,
        attachment_type=attachment_type,
        s3_key=f"key-{uuid4()}",
        mime_type="image/jpeg",
        original_filename="photo.jpg",
        size=2048,
    )
    attachment.attachment_status = status
    if width and height:
        attachment.set_resolution(width, height)
    return attachment


def make_message(
    content: str | None = "hello",
    message_type: MessageType = MessageType.TEXT,
    attachments: list[MessageAttachment] | None = None,
    author_id: int = 7,
) -> Message:
    message = Message.create(
        sender_id=author_id,
        chat_id=uuid4(),
        seq=3,
        content=content,
        message_type=message_type,
        reply_to_id=uuid4() if message_type == MessageType.REPLY else None,
        attachments=attachments,
    )
    message.pull_events()
    return message


def make_group() -> Chat:
    chat = Chat.create(created_by=1, members_ids=[2, 3], chat_type=ChatType.GROUP, name="g")
    chat.pull_events()
    return chat


@pytest.mark.unit
@pytest.mark.chats
class TestForwardCopy:

    def test_forward_points_to_the_original_and_keeps_content(self) -> None:
        source = make_message("original")
        target_chat = uuid4()

        copy = Message.create_forward(source, sender_id=1, chat_id=target_chat, seq=10)

        assert copy.type == MessageType.FORWARD
        assert copy.chat_id == target_chat
        assert copy.seq == 10
        assert copy.author_id == 1
        assert copy.content == "original"
        assert copy.forwarded_from_chat_id == source.chat_id
        assert copy.forwarded_from_message_id == source.id
        assert copy.forwarded_from_author_id == 7

    def test_forward_of_a_forward_keeps_pointing_at_the_first_origin(self) -> None:
        origin = make_message("first")
        hop = Message.create_forward(origin, sender_id=2, chat_id=uuid4(), seq=1)

        copy = Message.create_forward(hop, sender_id=3, chat_id=uuid4(), seq=1)

        assert copy.forwarded_from_message_id == origin.id
        assert copy.forwarded_from_chat_id == origin.chat_id
        assert copy.forwarded_from_author_id == origin.author_id

    def test_hide_author_produces_a_plain_copy(self) -> None:
        source = make_message("secret source")

        copy = Message.create_forward(source, sender_id=1, chat_id=uuid4(), seq=1, hide_author=True)

        assert copy.type == MessageType.TEXT
        assert copy.content == "secret source"
        assert copy.forwarded_from_chat_id is None
        assert copy.forwarded_from_message_id is None
        assert copy.forwarded_from_author_id is None

    def test_hide_author_turns_a_reply_into_text(self) -> None:
        source = make_message("answer", message_type=MessageType.REPLY)

        copy = Message.create_forward(source, sender_id=1, chat_id=uuid4(), seq=1, hide_author=True)

        assert copy.type == MessageType.TEXT
        assert copy.reply_to_id is None

    def test_hide_author_derives_voice_type_from_a_forwarded_voice(self) -> None:
        voice = make_message(
            None,
            message_type=MessageType.VOICE,
            attachments=[make_attachment(AttachmentType.VOICE, width=None, height=None)],
        )
        hop = Message.create_forward(voice, sender_id=2, chat_id=uuid4(), seq=1)
        assert hop.type == MessageType.FORWARD

        copy = Message.create_forward(hop, sender_id=3, chat_id=uuid4(), seq=1, hide_author=True)

        assert copy.type == MessageType.VOICE
        assert len(copy.attachments) == 1

    def test_album_keeps_order_and_dimensions(self) -> None:
        album = [make_attachment(width=100 + index, height=200 + index) for index in range(4)]
        source = make_message("album", message_type=MessageType.IMAGE, attachments=list(reversed(album)))
        target_chat = uuid4()

        copy = Message.create_forward(source, sender_id=1, chat_id=target_chat, seq=1)

        assert [a.source_attachment_id for a in copy.attachments] == [a.id for a in album]
        assert [(a.width, a.height) for a in copy.attachments] == [(a.width, a.height) for a in album]
        assert all(a.chat_id == target_chat for a in copy.attachments)
        assert all(a.attachment_status == AttachmentStatus.SUCCESS for a in copy.attachments)

    def test_unfinished_attachments_are_not_copied(self) -> None:
        ready = make_attachment()
        pending = make_attachment(status=AttachmentStatus.PENDING)
        source = make_message("mix", message_type=MessageType.IMAGE, attachments=[ready])
        source.attachments.append(pending)

        copy = Message.create_forward(source, sender_id=1, chat_id=uuid4(), seq=1)

        assert [a.source_attachment_id for a in copy.attachments] == [ready.id]

    def test_notify_flag_travels_in_the_sent_event(self) -> None:
        source = make_message("x")

        silent = Message.create_forward(source, sender_id=1, chat_id=uuid4(), seq=1, notify=False)
        loud = Message.create_forward(source, sender_id=1, chat_id=uuid4(), seq=2)

        (silent_event,) = silent.pull_events()
        (loud_event,) = loud.pull_events()
        assert isinstance(silent_event, SendedMessageEvent)
        assert silent_event.notify is False
        assert isinstance(loud_event, SendedMessageEvent)
        assert loud_event.notify is True

    def test_forwardable_rules(self) -> None:
        assert make_message("text").is_forwardable

        pending_only = make_message(None, message_type=MessageType.IMAGE, attachments=[])
        pending_only.attachments.append(make_attachment(status=AttachmentStatus.PENDING))
        assert not pending_only.is_forwardable

        system = Message.create_system(
            actor_id=1, chat_id=uuid4(), seq=1, action=SystemMessageAction.MESSAGE_PINNED
        )
        assert not system.is_forwardable

        deleted = make_message("bye")
        deleted.delete(deleted_by=7)
        assert not deleted.is_forwardable


@pytest.mark.unit
@pytest.mark.chats
class TestPinModel:

    def test_system_notice_carries_action_and_points_at_the_pinned_message(self) -> None:
        pinned_id = uuid7()
        notice = Message.create_system(
            actor_id=5,
            chat_id=uuid4(),
            seq=12,
            action=SystemMessageAction.MESSAGE_PINNED,
            reply_to_id=pinned_id,
        )

        assert notice.type == MessageType.SYSTEM
        assert notice.action == SystemMessageAction.MESSAGE_PINNED
        assert notice.reply_to_id == pinned_id
        assert notice.content is None
        (event,) = notice.pull_events()
        assert isinstance(event, SendedMessageEvent)
        assert event.message_type == "system"

    def test_pin_registers_event_with_message_seq(self) -> None:
        chat = make_group()
        message = make_message("pin me")
        message.chat_id = chat.id

        pin = chat.pin_message(message, pinned_by=1, pinned_count=0)

        assert pin.chat_id == chat.id
        assert pin.message_id == message.id
        assert pin.message_seq == message.seq
        (event,) = chat.pull_events()
        assert isinstance(event, PinnedMessageEvent)
        assert event.message_id == str(message.id)
        assert event.seq == message.seq
        assert event.pinned_by == 1

    def test_pin_from_another_chat_is_not_found(self) -> None:
        chat = make_group()

        with pytest.raises(NotFoundMessageError):
            chat.pin_message(make_message("elsewhere"), pinned_by=1, pinned_count=0)

    def test_system_message_cannot_be_pinned(self) -> None:
        chat = make_group()
        notice = Message.create_system(
            actor_id=1, chat_id=chat.id, seq=1, action=SystemMessageAction.MESSAGE_PINNED
        )

        with pytest.raises(InvalidMessageError):
            chat.pin_message(notice, pinned_by=1, pinned_count=0)

    def test_pin_limit(self) -> None:
        chat = make_group()
        message = make_message("one too many")
        message.chat_id = chat.id

        with pytest.raises(PinnedMessagesLimitExceededError):
            chat.pin_message(message, pinned_by=1, pinned_count=chat_config.MAX_PINNED_MESSAGES)

        assert chat.pull_events() == []

    def test_unpin_registers_one_event_for_all_ids(self) -> None:
        chat = make_group()
        ids = [uuid7(), uuid7()]

        chat.unpin_messages(ids, unpinned_by=2, unpin_all=True)

        (event,) = chat.pull_events()
        assert isinstance(event, UnpinnedMessagesEvent)
        assert event.message_ids == [str(i) for i in ids]
        assert event.all is True

    def test_unpin_nothing_registers_nothing(self) -> None:
        chat = make_group()
        chat.unpin_messages([], unpinned_by=2)
        assert chat.pull_events() == []


@pytest.mark.unit
@pytest.mark.chats
class TestReadMarksEligibility:

    def test_small_groups_and_supergroups_track_marks(self) -> None:
        group = make_group()
        assert group.tracks_read_marks

        group.member_count = chat_config.READ_MARKS_MAX_MEMBERS + 1
        assert not group.tracks_read_marks

        supergroup = Chat.create(created_by=1, members_ids=[2], chat_type=ChatType.SUPERGROUP, name="s")
        assert supergroup.tracks_read_marks

    def test_direct_and_channels_do_not_track_marks(self) -> None:
        direct = Chat.create(created_by=1, members_ids=[2], chat_type=ChatType.DIRECT)
        channel = Chat.create(created_by=1, members_ids=[2], chat_type=ChatType.CHANNEL, name="c")

        assert not direct.tracks_read_marks
        assert not channel.tracks_read_marks
