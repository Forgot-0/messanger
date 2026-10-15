from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.messages.delete import DeleteMessageCommand, DeleteMessageCommandHandler
from app.chats.commands.pins.pin import PinMessageCommand, PinMessageCommandHandler
from app.chats.commands.pins.unpin import UnpinMessagesCommand, UnpinMessagesCommandHandler
from app.chats.config import chat_config
from app.chats.exceptions import (
    AccessDeniedChatError,
    InvalidMessageError,
    NotChatMemberError,
    NotFoundMessageError,
    PinnedMessagesLimitExceededError,
)
from app.chats.models.chat import Chat
from app.chats.models.message import (
    Message,
    MessageType,
    PinnedMessageEvent,
    SendedMessageEvent,
    SystemMessageAction,
    UnpinnedMessagesEvent,
)
from app.chats.models.pinned_message import ChatPinnedMessage
from app.chats.queries.pins.get_list import GetPinnedMessagesQuery, GetPinnedMessagesQueryHandler
from app.core.services.auth.dto import UserJWTData
from tests.mocks import RecordingEventBus


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestPinnedMessages:

    @pytest.fixture
    async def pin(self, request_container: AsyncContainer) -> PinMessageCommandHandler:
        return await request_container.get(PinMessageCommandHandler)

    @pytest.fixture
    async def unpin(self, request_container: AsyncContainer) -> UnpinMessagesCommandHandler:
        return await request_container.get(UnpinMessagesCommandHandler)

    @pytest.fixture
    async def pinned(self, request_container: AsyncContainer) -> GetPinnedMessagesQueryHandler:
        return await request_container.get(GetPinnedMessagesQueryHandler)

    async def _pins(self, db_session: AsyncSession, chat: Chat) -> list[ChatPinnedMessage]:
        result = await db_session.execute(
            select(ChatPinnedMessage).where(ChatPinnedMessage.chat_id == chat.id)
        )
        return list(result.scalars().all())

    async def test_pin_stores_pin_posts_notice_and_emits_events(
        self,
        pin: PinMessageCommandHandler,
        group_chat: Chat,
        create_message,
        make_user_jwt,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        target = await create_message(group_chat, make_user_jwt(id="2"), "important")
        mock_event_bus.clear()

        dto = await pin.handle(
            PinMessageCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=target.id)
        )

        assert dto.message.id == target.id
        assert dto.pinned_by == 1
        assert [p.message_id for p in await self._pins(db_session, group_chat)] == [target.id]

        pinned_event = mock_event_bus.one_of_type(PinnedMessageEvent)
        assert pinned_event.message_id == str(target.id)
        assert pinned_event.seq == target.seq
        assert pinned_event.pinned_by == 1

        sent = mock_event_bus.one_of_type(SendedMessageEvent)
        assert sent.message_type == "system"
        notice = (
            await db_session.execute(select(Message).where(Message.id == sent.message_id))
        ).scalar_one()
        assert notice.type == MessageType.SYSTEM
        assert notice.action == SystemMessageAction.MESSAGE_PINNED
        assert notice.reply_to_id == target.id
        assert notice.author_id == 1
        assert notice.seq == target.seq + 1

    async def test_pinning_twice_is_idempotent(
        self,
        pin: PinMessageCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        target = await create_message(group_chat, user_jwt, "once")
        command = PinMessageCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=target.id)

        first = await pin.handle(command)
        mock_event_bus.clear()
        second = await pin.handle(command)

        assert second.pinned_at == first.pinned_at
        assert mock_event_bus.published_events == []
        notices = await db_session.execute(
            select(Message).where(Message.chat_id == group_chat.id, Message.type == MessageType.SYSTEM)
        )
        assert len(notices.scalars().all()) == 1

    async def test_plain_member_cannot_pin(
        self,
        pin: PinMessageCommandHandler,
        group_chat: Chat,
        create_message,
        make_user_jwt,
        user_jwt: UserJWTData,
    ) -> None:
        target = await create_message(group_chat, user_jwt, "x")

        with pytest.raises(AccessDeniedChatError):
            await pin.handle(PinMessageCommand(
                user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id, message_id=target.id
            ))

        with pytest.raises(NotChatMemberError):
            await pin.handle(PinMessageCommand(
                user_jwt_data=make_user_jwt(id="42"), chat_id=group_chat.id, message_id=target.id
            ))

    async def test_both_sides_of_a_direct_chat_can_pin(
        self,
        pin: PinMessageCommandHandler,
        direct_chat: Chat,
        create_message,
        make_user_jwt,
        user_jwt: UserJWTData,
    ) -> None:
        target = await create_message(direct_chat, user_jwt, "for both")

        dto = await pin.handle(PinMessageCommand(
            user_jwt_data=make_user_jwt(id="2"), chat_id=direct_chat.id, message_id=target.id
        ))

        assert dto.pinned_by == 2

    async def test_cannot_pin_a_notice_or_a_foreign_message(
        self,
        pin: PinMessageCommandHandler,
        create_group_chat,
        create_message,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        chat = await create_group_chat([2])
        other = await create_group_chat([2])
        target = await create_message(chat, user_jwt, "x")
        foreign = await create_message(other, user_jwt, "y")
        await pin.handle(PinMessageCommand(user_jwt_data=user_jwt, chat_id=chat.id, message_id=target.id))
        notice_id = UUID(mock_event_bus.one_of_type(SendedMessageEvent).message_id)

        with pytest.raises(InvalidMessageError):
            await pin.handle(PinMessageCommand(user_jwt_data=user_jwt, chat_id=chat.id, message_id=notice_id))

        with pytest.raises(NotFoundMessageError):
            await pin.handle(PinMessageCommand(user_jwt_data=user_jwt, chat_id=chat.id, message_id=foreign.id))

    async def test_pin_limit(
        self,
        pin: PinMessageCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(chat_config, "MAX_PINNED_MESSAGES", 2)
        messages = [await create_message(group_chat, user_jwt, f"m{i}") for i in range(3)]
        for message in messages[:2]:
            await pin.handle(PinMessageCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=message.id))

        with pytest.raises(PinnedMessagesLimitExceededError) as exc:
            await pin.handle(
                PinMessageCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=messages[2].id)
            )
        assert exc.value.detail["limit"] == 2

    async def test_unpin_one_and_unpin_all(
        self,
        pin: PinMessageCommandHandler,
        unpin: UnpinMessagesCommandHandler,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        messages = [await create_message(group_chat, user_jwt, f"m{i}") for i in range(3)]
        for message in messages:
            await pin.handle(PinMessageCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=message.id))
        mock_event_bus.clear()

        await unpin.handle(
            UnpinMessagesCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=messages[0].id)
        )
        await unpin.handle(
            UnpinMessagesCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=messages[0].id)
        )

        single = mock_event_bus.one_of_type(UnpinnedMessagesEvent)
        assert single.message_ids == [str(messages[0].id)]
        assert single.all is False

        mock_event_bus.clear()
        await unpin.handle(UnpinMessagesCommand(user_jwt_data=user_jwt, chat_id=group_chat.id))

        everything = mock_event_bus.one_of_type(UnpinnedMessagesEvent)
        assert sorted(everything.message_ids) == sorted(str(m.id) for m in messages[1:])
        assert everything.all is True
        assert await self._pins(db_session, group_chat) == []

    async def test_member_cannot_unpin(
        self,
        pin: PinMessageCommandHandler,
        unpin: UnpinMessagesCommandHandler,
        group_chat: Chat,
        create_message,
        make_user_jwt,
        user_jwt: UserJWTData,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "stay")
        await pin.handle(PinMessageCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=message.id))

        with pytest.raises(AccessDeniedChatError):
            await unpin.handle(UnpinMessagesCommand(user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id))

    async def test_deleting_a_pinned_message_unpins_it(
        self,
        pin: PinMessageCommandHandler,
        request_container: AsyncContainer,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "soon gone")
        # Фабрика не забирает событие отправки, а identity map сессии вернёт хендлеру тот же объект.
        message.pull_events()
        await pin.handle(PinMessageCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=message.id))
        mock_event_bus.clear()
        delete = await request_container.get(DeleteMessageCommandHandler)

        await delete.handle(
            DeleteMessageCommand(chat_id=group_chat.id, message_id=message.id, user_jwt_data=user_jwt)
        )

        assert mock_event_bus.names() == ["chats.message.deleted", "chats.message.unpinned"]
        assert mock_event_bus.one_of_type(UnpinnedMessagesEvent).message_ids == [str(message.id)]
        assert await self._pins(db_session, group_chat) == []

    async def test_deleting_an_unpinned_message_emits_no_unpin(
        self,
        request_container: AsyncContainer,
        group_chat: Chat,
        create_message,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        message = await create_message(group_chat, user_jwt, "plain")
        message.pull_events()
        mock_event_bus.clear()
        delete = await request_container.get(DeleteMessageCommandHandler)

        await delete.handle(
            DeleteMessageCommand(chat_id=group_chat.id, message_id=message.id, user_jwt_data=user_jwt)
        )

        assert mock_event_bus.names() == ["chats.message.deleted"]

    async def test_list_is_newest_message_first_with_cursor_and_total(
        self,
        pin: PinMessageCommandHandler,
        pinned: GetPinnedMessagesQueryHandler,
        group_chat: Chat,
        create_message,
        make_user_jwt,
        user_jwt: UserJWTData,
    ) -> None:
        messages = [await create_message(group_chat, user_jwt, f"m{i}") for i in range(3)]
        for message in (messages[1], messages[0], messages[2]):
            await pin.handle(PinMessageCommand(user_jwt_data=user_jwt, chat_id=group_chat.id, message_id=message.id))
        reader = make_user_jwt(id="2")

        first = await pinned.handle(GetPinnedMessagesQuery(user_jwt_data=reader, chat_id=group_chat.id, limit=2))

        assert [item.message.content for item in first.items] == ["m2", "m1"]
        assert first.total == 3
        assert first.has_next is True
        assert first.next_cursor == messages[1].seq

        second = await pinned.handle(GetPinnedMessagesQuery(
            user_jwt_data=reader, chat_id=group_chat.id, limit=2, before_seq=first.next_cursor
        ))
        assert [item.message.content for item in second.items] == ["m0"]
        assert second.has_next is False
        assert second.next_cursor is None

    async def test_list_requires_membership(
        self,
        pinned: GetPinnedMessagesQueryHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        with pytest.raises(NotChatMemberError):
            await pinned.handle(GetPinnedMessagesQuery(user_jwt_data=make_user_jwt(id="42"), chat_id=group_chat.id))
