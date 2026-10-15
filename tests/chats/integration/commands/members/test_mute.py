from datetime import timedelta

import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.commands.chats.mute_member import MuteMemberCommand, MuteMemberCommandHandler
from app.chats.commands.chats.unban_member import UnbanMemberCommand, UnbanMemberCommandHandler
from app.chats.commands.chats.unmute_member import UnmuteMemberCommand, UnmuteMemberCommandHandler
from app.chats.commands.messages.send import SendMessageCommand, SendMessageCommandHandler
from app.chats.exceptions import AccessDeniedChatError, NotChatMemberError
from app.chats.models.chat import BannedChatMemberEvent, Chat, MutedChatMemberEvent
from app.chats.models.chat_members import PERMANENT_UNTIL
from app.chats.repositories.chat import ChatRepository
from app.core.services.auth.dto import UserJWTData
from app.core.utils import now_utc
from tests.mocks import RecordingEventBus


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestMuteMember:

    @pytest.fixture
    async def mute(self, request_container: AsyncContainer) -> MuteMemberCommandHandler:
        return await request_container.get(MuteMemberCommandHandler)

    @pytest.fixture
    async def unmute(self, request_container: AsyncContainer) -> UnmuteMemberCommandHandler:
        return await request_container.get(UnmuteMemberCommandHandler)

    async def test_owner_mutes_member_temporarily(
        self,
        mute: MuteMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        until = now_utc() + timedelta(hours=2)

        await mute.handle(MuteMemberCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2, muted_until=until,
        ))

        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        assert member.is_muted is True
        assert member.muted_until == until

        event = mock_event_bus.one_of_type(MutedChatMemberEvent)
        assert event.target_user_id == 2
        assert event.mute is True
        assert event.muted_until == until.isoformat()

    async def test_mute_without_deadline_is_permanent(
        self,
        mute: MuteMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        await mute.handle(MuteMemberCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2,
        ))

        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        assert member.muted_until == PERMANENT_UNTIL

    async def test_muted_member_cannot_send(
        self,
        mute: MuteMemberCommandHandler,
        request_container: AsyncContainer,
        group_chat: Chat,
        user_jwt: UserJWTData,
        make_user_jwt,
    ) -> None:
        await mute.handle(MuteMemberCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2,
        ))

        send = await request_container.get(SendMessageCommandHandler)
        with pytest.raises(AccessDeniedChatError):
            await send.handle(SendMessageCommand(
                chat_id=group_chat.id, content="hi", user_jwt_data=make_user_jwt(id="2"),
            ))

    async def test_unmute_restores_sending_and_emits_event(
        self,
        mute: MuteMemberCommandHandler,
        unmute: UnmuteMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        await mute.handle(MuteMemberCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2,
        ))
        mock_event_bus.clear()

        await unmute.handle(UnmuteMemberCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2,
        ))

        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        assert member.is_muted is False
        assert member.muted_until is None
        event = mock_event_bus.one_of_type(MutedChatMemberEvent)
        assert event.mute is False

    async def test_unmute_of_not_muted_member_is_silent_noop(
        self,
        unmute: UnmuteMemberCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        await unmute.handle(UnmuteMemberCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2,
        ))

        assert mock_event_bus.of_type(MutedChatMemberEvent) == []

    async def test_regular_member_cannot_mute(
        self,
        mute: MuteMemberCommandHandler,
        group_chat: Chat,
        make_user_jwt,
    ) -> None:
        with pytest.raises(AccessDeniedChatError):
            await mute.handle(MuteMemberCommand(
                user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id, target_user_id=3,
            ))

    async def test_cannot_mute_self(
        self,
        mute: MuteMemberCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(AccessDeniedChatError):
            await mute.handle(MuteMemberCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=int(user_jwt.id),
            ))

    async def test_mute_non_member(
        self,
        mute: MuteMemberCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
    ) -> None:
        with pytest.raises(NotChatMemberError):
            await mute.handle(MuteMemberCommand(
                user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=999,
            ))


@pytest.mark.integration
@pytest.mark.chats
@pytest.mark.asyncio
class TestUnbanMember:

    @pytest.fixture
    async def handler(self, request_container: AsyncContainer) -> UnbanMemberCommandHandler:
        return await request_container.get(UnbanMemberCommandHandler)

    async def test_owner_unbans_member(
        self,
        handler: UnbanMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        member = await chat_repository.get_member_chat(group_chat.id, 2)
        assert member is not None
        member.ban(banned_by=int(user_jwt.id))
        await db_session.commit()

        await handler.handle(UnbanMemberCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2,
        ))

        refreshed = await chat_repository.get_member_chat(group_chat.id, 2)
        assert refreshed is not None
        assert refreshed.is_banned is False
        event = mock_event_bus.one_of_type(BannedChatMemberEvent)
        assert event.ban is False
        assert event.target_user_id == 2

    async def test_unban_of_active_member_is_noop(
        self,
        handler: UnbanMemberCommandHandler,
        group_chat: Chat,
        user_jwt: UserJWTData,
        mock_event_bus: RecordingEventBus,
    ) -> None:
        await handler.handle(UnbanMemberCommand(
            user_jwt_data=user_jwt, chat_id=group_chat.id, target_user_id=2,
        ))

        assert mock_event_bus.of_type(BannedChatMemberEvent) == []

    async def test_member_without_ban_permission_cannot_unban(
        self,
        handler: UnbanMemberCommandHandler,
        chat_repository: ChatRepository,
        group_chat: Chat,
        user_jwt: UserJWTData,
        db_session: AsyncSession,
        make_user_jwt,
    ) -> None:
        member = await chat_repository.get_member_chat(group_chat.id, 3)
        assert member is not None
        member.ban(banned_by=int(user_jwt.id))
        await db_session.commit()

        with pytest.raises(AccessDeniedChatError):
            await handler.handle(UnbanMemberCommand(
                user_jwt_data=make_user_jwt(id="2"), chat_id=group_chat.id, target_user_id=3,
            ))
