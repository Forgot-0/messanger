from uuid import uuid4

import pytest
from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.messages.forward_many import ForwardMessagesCommand, ForwardMessagesCommandHandler
from app.chats.exceptions import (
    AccessDeniedChatError,
    NotChatMemberError,
    NotFoundMessageError,
    SlowModeMultipleMessagesError,
)
from app.chats.models.attachment import AttachmentStatus, AttachmentType, MessageAttachment
from app.chats.models.chat import Chat, ChatType
from app.chats.models.message import Message, MessageType, SendedMessageEvent
from app.core.services.auth.dto import UserJWTData
from tests.mocks import RecordingEventBus


@pytest.fixture
def create_album(db_session: AsyncSession):
    async def _create(chat: Chat, author_id: int, size: int) -> Message:
        attachments = []
        for index in range(size):
            attachment = MessageAttachment.create(
                chat_id=chat.id,
                uploader_id=author_id,
                attachment_type=AttachmentType.IMAGE,
                s3_key=f"album/{uuid4()}.jpg",
                mime_type="image/jpeg",
                original_filename=f"{index}.jpg",
                size=1024,
            )
            attachment.attachment_status = AttachmentStatus.SUCCESS
            attachment.set_resolution(800 + index, 600 + index)
            attachments.append(attachment)

        chat.seq_counter += 1
        message = Message.create(
            sender_id=author_id,
            chat_id=chat.id,
            seq=chat.seq_counter,
            content="album caption",
            message_type=MessageType.IMAGE,
            attachments=attachments,
        )
        db_session.add(message)
        await db_session.commit()
        return message

    return _create


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestForwardMessagesCommand:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> ForwardMessagesCommandHandler:
        return await request_container.get(ForwardMessagesCommandHandler)

    async def test_forwards_in_source_order_with_consecutive_seqs(
        self,
        handler: ForwardMessagesCommandHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
        make_user_jwt,
        db_session: AsyncSession,
    ) -> None:
        src = await create_group_chat([2, 3])
        tgt = await create_group_chat([2])
        first = await create_message(src, user_jwt, "one")
        second = await create_message(src, make_user_jwt(id="2"), "two")
        third = await create_message(src, user_jwt, "three")
        seq_before = tgt.seq_counter

        result = await handler.handle(ForwardMessagesCommand(
            user_jwt_data=user_jwt,
            source_chat_id=src.id,
            source_message_ids=[third.id, first.id, second.id, first.id],
            target_chat_id=tgt.id,
        ))

        assert [m.content for m in result.messages] == ["one", "two", "three"]
        assert [m.forwarded_from_message_id for m in result.messages] == [first.id, second.id, third.id]
        assert [m.forwarded_from_author_id for m in result.messages] == [1, 2, 1]
        assert all(m.type == MessageType.FORWARD and m.author_id == 1 for m in result.messages)
        assert [m.seq for m in result.messages] == [seq_before + 1, seq_before + 2, seq_before + 3]

        await db_session.refresh(tgt)
        assert tgt.seq_counter == seq_before + 3

    async def test_album_stays_one_message_with_order_and_dimensions(
        self,
        handler: ForwardMessagesCommandHandler,
        create_group_chat,
        create_album,
        user_jwt: UserJWTData,
    ) -> None:
        src = await create_group_chat([2])
        tgt = await create_group_chat([2])
        album = await create_album(src, author_id=1, size=4)

        result = await handler.handle(ForwardMessagesCommand(
            user_jwt_data=user_jwt,
            source_chat_id=src.id,
            source_message_ids=[album.id],
            target_chat_id=tgt.id,
        ))

        (forwarded,) = result.messages
        assert forwarded.content == "album caption"
        assert [a.original_filename for a in forwarded.attachments] == ["0.jpg", "1.jpg", "2.jpg", "3.jpg"]
        assert [(a.width, a.height) for a in forwarded.attachments] == [
            (800, 600), (801, 601), (802, 602), (803, 603)
        ]
        assert all(a.chat_id == tgt.id for a in forwarded.attachments)
        assert all(a.url for a in forwarded.attachments)

    async def test_hide_author_sends_plain_copies(
        self,
        handler: ForwardMessagesCommandHandler,
        create_group_chat,
        create_message,
        create_album,
        make_user_jwt,
        user_jwt: UserJWTData,
    ) -> None:
        src = await create_group_chat([2])
        tgt = await create_group_chat([2])
        text = await create_message(src, make_user_jwt(id="2"), "anonymous")
        album = await create_album(src, author_id=2, size=2)

        result = await handler.handle(ForwardMessagesCommand(
            user_jwt_data=user_jwt,
            source_chat_id=src.id,
            source_message_ids=[text.id, album.id],
            target_chat_id=tgt.id,
            hide_author=True,
        ))

        assert [m.type for m in result.messages] == [MessageType.TEXT, MessageType.IMAGE]
        assert all(m.author_id == 1 for m in result.messages)
        assert all(
            m.forwarded_from_author_id is None
            and m.forwarded_from_message_id is None
            and m.forwarded_from_chat_id is None
            for m in result.messages
        )
        assert len(result.messages[1].attachments) == 2

    async def test_comment_goes_first_and_only_the_last_message_pushes(
        self,
        handler: ForwardMessagesCommandHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        src = await create_group_chat([2])
        tgt = await create_group_chat([2])
        messages = [await create_message(src, user_jwt, f"m{i}") for i in range(2)]
        mock_event_bus.clear()

        result = await handler.handle(ForwardMessagesCommand(
            user_jwt_data=user_jwt,
            source_chat_id=src.id,
            source_message_ids=[m.id for m in messages],
            target_chat_id=tgt.id,
            comment="  look at this  ",
        ))

        assert [(m.type, m.content) for m in result.messages] == [
            (MessageType.TEXT, "look at this"),
            (MessageType.FORWARD, "m0"),
            (MessageType.FORWARD, "m1"),
        ]
        sent = mock_event_bus.of_type(SendedMessageEvent)
        assert [event.message_id for event in sent] == [str(m.id) for m in result.messages]
        assert [event.notify for event in sent] == [False, False, True]

    async def test_deleted_and_unknown_ids_are_skipped(
        self,
        handler: ForwardMessagesCommandHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        src = await create_group_chat([2])
        tgt = await create_group_chat([2])
        gone = await create_message(src, user_jwt, "gone")
        kept = await create_message(src, user_jwt, "kept")
        gone.delete(deleted_by=1)
        await db_session.commit()

        result = await handler.handle(ForwardMessagesCommand(
            user_jwt_data=user_jwt,
            source_chat_id=src.id,
            source_message_ids=[gone.id, uuid4(), kept.id],
            target_chat_id=tgt.id,
        ))

        assert [m.content for m in result.messages] == ["kept"]

        with pytest.raises(NotFoundMessageError):
            await handler.handle(ForwardMessagesCommand(
                user_jwt_data=user_jwt,
                source_chat_id=src.id,
                source_message_ids=[gone.id, uuid4()],
                target_chat_id=tgt.id,
            ))

    async def test_messages_of_another_chat_are_not_forwarded(
        self,
        handler: ForwardMessagesCommandHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
    ) -> None:
        src = await create_group_chat([2])
        other = await create_group_chat([2])
        tgt = await create_group_chat([2])
        foreign = await create_message(other, user_jwt, "from other chat")

        with pytest.raises(NotFoundMessageError):
            await handler.handle(ForwardMessagesCommand(
                user_jwt_data=user_jwt,
                source_chat_id=src.id,
                source_message_ids=[foreign.id],
                target_chat_id=tgt.id,
            ))

    async def test_slow_mode_allows_a_single_message_but_not_a_batch(
        self,
        handler: ForwardMessagesCommandHandler,
        create_group_chat,
        create_message,
        make_user_jwt,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        src = await create_group_chat([2])
        tgt = await create_group_chat([2], slow_mode=60)
        messages = [await create_message(src, user_jwt, f"m{i}") for i in range(2)]
        member = make_user_jwt(id="2")

        with pytest.raises(SlowModeMultipleMessagesError):
            await handler.handle(ForwardMessagesCommand(
                user_jwt_data=member,
                source_chat_id=src.id,
                source_message_ids=[m.id for m in messages],
                target_chat_id=tgt.id,
            ))

        stored = await db_session.execute(select(Message).where(Message.chat_id == tgt.id))
        assert stored.scalars().all() == []

        single = await handler.handle(ForwardMessagesCommand(
            user_jwt_data=member,
            source_chat_id=src.id,
            source_message_ids=[messages[0].id],
            target_chat_id=tgt.id,
        ))
        assert len(single.messages) == 1

    async def test_outsider_of_the_source_chat_is_rejected(
        self,
        handler: ForwardMessagesCommandHandler,
        create_group_chat,
        create_message,
        make_user_jwt,
        user_jwt: UserJWTData,
    ) -> None:
        src = await create_group_chat([2])
        tgt = await create_group_chat([3])
        message = await create_message(src, user_jwt, "private")

        with pytest.raises(NotChatMemberError):
            await handler.handle(ForwardMessagesCommand(
                user_jwt_data=make_user_jwt(id="3"),
                source_chat_id=src.id,
                source_message_ids=[message.id],
                target_chat_id=tgt.id,
            ))

    async def test_cannot_forward_into_a_channel_as_a_subscriber(
        self,
        handler: ForwardMessagesCommandHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
    ) -> None:
        src = await create_group_chat([2])
        channel = Chat.create(created_by=2, members_ids=[1], chat_type=ChatType.CHANNEL, name="news")
        db_session.add(channel)
        await db_session.commit()
        message = await create_message(src, user_jwt, "hi")

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(ForwardMessagesCommand(
                user_jwt_data=user_jwt,
                source_chat_id=src.id,
                source_message_ids=[message.id],
                target_chat_id=channel.id,
            ))
